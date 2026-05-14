"""Feishu (Lark) uploader module for uploading reports to a specific folder."""

import logging
import os
import time
import requests
from requests_toolbelt import MultipartEncoder
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ImportStatus(Enum):
    """Import task status enumeration."""
    INIT = 0
    PROCESSING = 1
    SUCCESS = 2
    FAILED = 3


@dataclass
class ImportResult:
    """Result of a file import operation."""
    success: bool
    file_name: str
    doc_token: Optional[str] = None
    doc_url: Optional[str] = None
    error_msg: Optional[str] = None


class FeishuUploader:
    """Handles authentication and file uploads to Feishu Drive."""

    BASE_URL = "https://open.feishu.cn/open-apis"
    IMPORT_POLL_INTERVAL = 2
    IMPORT_MAX_RETRIES = 30

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        upload_folder: Optional[str] = None,
        archive_folder: Optional[str] = None,
    ) -> None:
        """Initialize FeishuUploader.

        Args:
            app_id: Feishu App ID. If None, reads from APP_ID env var.
            app_secret: Feishu App Secret. If None, reads from APP_SECRET env var.
            upload_folder: Target folder token for uploads.
            archive_folder: Target Feishu folder token to move converted documents.
        """
        self.app_id = app_id or os.environ.get("APP_ID")
        self.app_secret = app_secret or os.environ.get("APP_SECRET")
        self.upload_folder = upload_folder or os.environ.get("FEISHU_UPLOAD_FOLDER")
        self.archive_folder = archive_folder or os.environ.get("FEISHU_ARCHIVE_FOLDER")
        self._tenant_access_token: Optional[str] = None

    def _get_tenant_access_token(self) -> Optional[str]:
        """Fetch the tenant access token using app_id and app_secret.

        Returns:
            The tenant access token, or None if failed.
        """
        if not self.app_id or not self.app_secret:
            logger.error("Feishu credentials (APP_ID, APP_SECRET) not provided.")
            return None

        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                self._tenant_access_token = data.get("tenant_access_token")
                return self._tenant_access_token
            else:
                logger.error("Failed to get Feishu tenant_access_token: %s", data.get("msg"))
                return None
        except Exception as e:
            logger.error("Error during Feishu authentication: %s", e)
            return None

    def upload_file(self, file_path: Path) -> Optional[str]:
        """Upload a file to the specified Feishu folder.

        Args:
            file_path: Path to the file to upload.

        Returns:
            The file token if upload was successful, None otherwise.
        """
        if not file_path.exists():
            logger.error("File to upload does not exist: %s", file_path)
            return None

        if not self.upload_folder:
            logger.error("Feishu folder token (FEISHU_UPLOAD_FOLDER) not provided.")
            return None

        token = self._get_tenant_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/drive/v1/files/upload_all"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        file_size = file_path.stat().st_size
        file_name = file_path.name

        try:
            with open(file_path, "rb") as f:
                form = {
                    'file_name': file_name,
                    'parent_type': 'explorer',
                    'parent_node': self.upload_folder,
                    'size': str(file_size),
                    'file': (file_name, f)
                }
                multi_form = MultipartEncoder(form)
                headers["Content-Type"] = multi_form.content_type

                response = requests.post(url, headers=headers, data=multi_form, timeout=60)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") == 0:
                    file_token = data.get("data", {}).get("file_token")
                    logger.info("Successfully uploaded %s to Feishu. File token: %s", file_name, file_token)
                    return file_token
                else:
                    logger.error("Failed to upload file to Feishu: %s (Code: %s)", data.get("msg"), data.get("code"))
                    return None
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error during Feishu file upload: %s. Response: %s", e, e.response.text)
            return None
        except Exception as e:
            logger.error("Error during Feishu file upload: %s", e)
            return None

    def _create_import_task(
        self,
        file_token: str,
        file_extension: str,
        target_type: str = "docx",
        file_name: Optional[str] = None
    ) -> Optional[str]:
        """Create an import task to convert uploaded file to Feishu document.

        Args:
            file_token: Token of the uploaded file.
            file_extension: Extension of the file (e.g., 'md', 'docx').
            target_type: Target document type ('docx', 'sheet', 'bitable').
            file_name: Name for the converted document.

        Returns:
            The import task ticket if successful, None otherwise.
        """
        token = self._get_tenant_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/drive/v1/import_tasks"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        payload = {
            "file_extension": file_extension,
            "file_token": file_token,
            "type": target_type,
            "point": {
                "mount_type": 1,
                "mount_key": self.upload_folder or ""
            }
        }

        if file_name:
            payload["file_name"] = file_name

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0:
                ticket = data.get("data", {}).get("ticket")
                return ticket
            else:
                logger.error("Failed to create import task: %s (Code: %s)", data.get("msg"), data.get("code"))
                return None
        except Exception as e:
            logger.error("Error creating import task: %s", e)
            return None

    def _get_import_result(self, ticket: str) -> Tuple[ImportStatus, Optional[Dict]]:
        """Query the import task result.

        Args:
            ticket: The import task ticket.

        Returns:
            Tuple of (status, result_data).
        """
        token = self._get_tenant_access_token()
        if not token:
            return ImportStatus.FAILED, None

        url = f"{self.BASE_URL}/drive/v1/import_tasks/{ticket}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0:
                result = data.get("data", {}).get("result", {})
                job_status = result.get("job_status")
                
                if job_status == 0:
                    return ImportStatus.INIT, result
                elif job_status == 1:
                    return ImportStatus.PROCESSING, result
                elif job_status == 2:
                    return ImportStatus.SUCCESS, result
                else:
                    return ImportStatus.FAILED, result
            else:
                logger.error("Failed to get import result: %s", data.get("msg"))
                return ImportStatus.FAILED, None
        except Exception as e:
            logger.error("Error querying import result: %s", e)
            return ImportStatus.FAILED, None

    def _wait_for_import(self, ticket: str) -> Tuple[bool, Optional[Dict]]:
        """Wait for the import task to complete.

        Args:
            ticket: The import task ticket.

        Returns:
            Tuple of (success, result_data).
        """
        for _ in range(self.IMPORT_MAX_RETRIES):
            status, result = self._get_import_result(ticket)
            
            if status == ImportStatus.SUCCESS:
                return True, result
            elif status == ImportStatus.FAILED:
                error_msg = result.get("job_error_msg") if result else "Unknown error"
                logger.error("Import task failed: %s", error_msg)
                return False, result
            
            time.sleep(self.IMPORT_POLL_INTERVAL)
        
        logger.error("Import task timed out after %d seconds", self.IMPORT_MAX_RETRIES * self.IMPORT_POLL_INTERVAL)
        return False, None

    def convert_to_docx(
        self,
        file_token: str,
        file_extension: str,
        file_name: Optional[str] = None
    ) -> ImportResult:
        """Convert an uploaded file to Feishu document.

        Args:
            file_token: Token of the uploaded file.
            file_extension: Extension of the file (e.g., 'md', 'docx').
            file_name: Name for the converted document.

        Returns:
            ImportResult with conversion details.
        """
        ticket = self._create_import_task(file_token, file_extension, "docx", file_name)
        if not ticket:
            return ImportResult(
                success=False,
                file_name=file_name or "unknown",
                error_msg="Failed to create import task"
            )

        success, result = self._wait_for_import(ticket)
        if success and result:
            return ImportResult(
                success=True,
                file_name=file_name or "unknown",
                doc_token=result.get("token"),
                doc_url=result.get("url")
            )
        else:
            return ImportResult(
                success=False,
                file_name=file_name or "unknown",
                error_msg=result.get("job_error_msg") if result else "Import timed out"
            )

    def upload_and_convert(
        self,
        file_path: Path,
        convert: bool = True,
        move_to_subdir: Optional[str] = None
    ) -> ImportResult:
        """Upload a file and optionally convert it to Feishu document.

        Args:
            file_path: Path to the file to upload.
            convert: Whether to convert to Feishu document after upload.
            move_to_subdir: Target Feishu folder token to move the uploaded file.
                           If None, uses the archive_subdir from initialization.

        Returns:
            ImportResult with upload and conversion details.
        """
        file_token = self.upload_file(file_path)
        if not file_token:
            return ImportResult(
                success=False,
                file_name=file_path.name,
                error_msg="Failed to upload file"
            )

        subdir = move_to_subdir or self.archive_folder
        if not convert:
            if subdir:
                self._move_feishu_document(file_token, "file", subdir)
            return ImportResult(
                success=True,
                file_name=file_path.name,
                doc_token=file_token
            )

        file_extension = file_path.suffix.lstrip('.').lower()
        result = self.convert_to_docx(file_token, file_extension, file_path.stem)

        if result.success and subdir:
            self._move_feishu_document(file_token, "file", subdir)

        return result

    def _move_feishu_document(
        self,
        doc_token: str,
        doc_type: str,
        target_folder_token: str
    ) -> bool:
        """Move a Feishu document to a target folder.

        Args:
            doc_token: Token of the document to move.
            doc_type: Type of the document (e.g., 'docx', 'sheet', 'bitable').
            target_folder_token: Token of the target folder.

        Returns:
            True if the document was moved successfully, False otherwise.
        """
        token = self._get_tenant_access_token()
        if not token:
            return False

        url = f"{self.BASE_URL}/drive/v1/files/{doc_token}/move"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        payload = {
            "type": doc_type,
            "folder_token": target_folder_token
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0:
                logger.info("Successfully moved file to archive folder")
                return True
            else:
                logger.error("Failed to move file: %s (Code: %s)", data.get("msg"), data.get("code"))
                return False
        except Exception as e:
            logger.error("Error moving file: %s", e)
            return False

    def convert_directory_md_files(
        self,
        directory: Path,
        move_to_subdir: Optional[str] = None
    ) -> List[ImportResult]:
        """Convert all markdown files in a directory to Feishu documents.

        This method uploads each .md file and converts it to a Feishu document.

        Args:
            directory: Path to the directory containing markdown files.
            move_to_subdir: Target Feishu folder token to move the converted documents.
                           If None, uses the archive_subdir from initialization.

        Returns:
            List of ImportResult for each file processed.
        """
        if not directory.exists() or not directory.is_dir():
            logger.error("Directory does not exist or is not a directory: %s", directory)
            return []

        md_files = list(directory.glob("*.md"))
        if not md_files:
            logger.info("No markdown files found in directory: %s", directory)
            return []

        logger.info("Found %d markdown files to convert", len(md_files))
        results: List[ImportResult] = []

        for md_file in md_files:
            logger.info("Processing: %s", md_file.name)
            result = self.upload_and_convert(md_file, convert=True, move_to_subdir=move_to_subdir)
            results.append(result)

            if result.success:
                logger.info("Successfully converted: %s -> %s", md_file.name, result.doc_url)
            else:
                logger.error("Failed to convert: %s - %s", md_file.name, result.error_msg)

        successful = sum(1 for r in results if r.success)
        logger.info("Conversion complete: %d/%d files converted successfully", successful, len(results))

        return results


if __name__ == "__main__":
    import argparse
    import sys
    from dotenv import load_dotenv

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Upload files to Feishu Drive and convert to Feishu documents.")
    parser.add_argument("--file", type=str, help="Path to a single file to upload")
    parser.add_argument("--dir", type=str, help="Path to directory containing markdown files to convert")
    parser.add_argument("--no-convert", action="store_true", help="Upload only without converting to Feishu document")
    parser.add_argument("--move-to-subdir", type=str, help="Target Feishu folder token to move converted documents")
    parser.add_argument("--env", type=str, default="configures\\.env", help="Path to .env file (default: .env)")

    args = parser.parse_args()
    args.file = "D:\\xugd\\learning\\python_study\\auo_analyze\\EmailExtractor\\Extracted\\test-min_summaries.md"
    args.env = "D:\\xugd\\learning\\python_study\\auo_analyze\\EmailExtractor\\configures\\.env"

    if not args.file and not args.dir:
        parser.error("Either --file or --dir must be specified")

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    uploader = FeishuUploader()

    if args.dir:
        directory = Path(args.dir)
        results = uploader.convert_directory_md_files(directory, move_to_subdir=args.move_to_subdir)
        
        print(f"\nConversion Results:")
        print("-" * 60)
        for result in results:
            if result.success:
                print(f"✓ {result.file_name}: {result.doc_url}")
            else:
                print(f"✗ {result.file_name}: {result.error_msg}")
        
        successful = sum(1 for r in results if r.success)
        print("-" * 60)
        print(f"Total: {successful}/{len(results)} files converted successfully")
        sys.exit(0 if successful == len(results) else 1)

    if args.file:
        file_to_upload = Path(args.file)
        result = uploader.upload_and_convert(file_to_upload, convert=not args.no_convert, move_to_subdir=args.move_to_subdir)
        
        if result.success:
            print(f"Successfully uploaded: {args.file}")
            if result.doc_url:
                print(f"Feishu Document URL: {result.doc_url}")
            sys.exit(0)
        else:
            print(f"Failed to upload: {args.file}")
            print(f"Error: {result.error_msg}")
            sys.exit(1)

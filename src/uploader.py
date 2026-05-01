"""Feishu (Lark) uploader module for uploading reports to a specific folder."""

import logging
import os
import requests
from requests_toolbelt import MultipartEncoder
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FeishuUploader:
    """Handles authentication and file uploads to Feishu Drive."""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        folder_token: Optional[str] = None,
    ) -> None:
        """Initialize FeishuUploader.

        Args:
            app_id: Feishu App ID. If None, reads from APP_ID env var.
            app_secret: Feishu App Secret. If None, reads from APP_SECRET env var.
            folder_token: Target folder token. If None, reads from FEISHU_FOLDER_TOKEN env var.
        """
        self.app_id = app_id or os.environ.get("APP_ID")
        self.app_secret = app_secret or os.environ.get("APP_SECRET")
        self.folder_token = folder_token or os.environ.get("FEISHU_FOLDER_TOKEN")
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

    def upload_file(self, file_path: Path) -> bool:
        """Upload a file to the specified Feishu folder.

        Args:
            file_path: Path to the file to upload.

        Returns:
            True if upload was successful, False otherwise.
        """
        if not file_path.exists():
            logger.error("File to upload does not exist: %s", file_path)
            return False

        if not self.folder_token:
            logger.error("Feishu folder token (FEISHU_FOLDER_TOKEN) not provided.")
            return False

        token = self._get_tenant_access_token()
        if not token:
            return False

        url = f"{self.BASE_URL}/drive/v1/files/upload_all"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        file_size = file_path.stat().st_size
        file_name = file_path.name

        payload = {
            "file_name": file_name,
            "parent_type": "explorer",
            "parent_node": self.folder_token,
            "size": str(file_size)
        }

        try:
            with open(file_path, "rb") as f:
                form = {
                    'file_name': file_name,
                    'parent_type': 'explorer',
                    'parent_node': self.folder_token,
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
                    return True
                else:
                    logger.error("Failed to upload file to Feishu: %s (Code: %s)", data.get("msg"), data.get("code"))
                    return False
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error during Feishu file upload: %s. Response: %s", e, e.response.text)
            return False
        except Exception as e:
            logger.error("Error during Feishu file upload: %s", e)
            return False


if __name__ == "__main__":
    import argparse
    import sys
    from dotenv import load_dotenv

    # Setup basic logging for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Upload a file to Feishu Drive.")
    parser.add_argument("--file", type=str, help="Path to the file to upload")
    parser.add_argument("--env", type=str, default=".env", help="Path to .env file (default: .env)")

    args = parser.parse_args()

    args.file = 'D:\\xugd\\ai_cc\\auo_analyze\\EmailExtractor\\Extracted\\2026-04-30_sub-7min_summaries.md'
    args.env = 'D:\\xugd\\ai_cc\\auo_analyze\\EmailExtractor\\.env'

    # Load environment variables from specified .env file
    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        # Fallback to default search if specified file doesn't exist
        load_dotenv()

    uploader = FeishuUploader()
    file_to_upload = Path(args.file)
    if uploader.upload_file(file_to_upload):
        print(f"Successfully uploaded: {args.file}")
        sys.exit(0)
    else:
        print(f"Failed to upload: {args.file}")
        sys.exit(1)

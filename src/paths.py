"""Path utilities for resolving application paths in both development and compiled modes.

When packaged with Nuitka, the executable's working directory may differ from
the executable location. This module provides utilities to correctly resolve
paths relative to the application base directory.
"""

import sys
from pathlib import Path
from typing import Optional

CONFIGURES_DIR = "configures"


def get_app_dir() -> Path:
    """Get the application base directory.

    In development mode: Returns the directory containing the main script.
    In Nuitka compiled mode: Returns the directory containing the executable.

    Returns:
        Path to the application base directory.
    """
    if hasattr(sys, "frozen") or "__compiled__" in globals():
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.parent.resolve()


def get_configures_dir() -> Path:
    """Get the configures directory.

    Returns:
        Path to the configures directory.
    """
    return get_app_dir() / CONFIGURES_DIR


def resolve_path(path: Optional[str | Path], base_dir: Optional[Path] = None) -> Path:
    """Resolve a path to an absolute path.

    If the path is already absolute, returns it as-is.
    If the path is relative, resolves it relative to the application base directory.

    Args:
        path: The path to resolve (string or Path).
        base_dir: Optional base directory. If None, uses get_app_dir().

    Returns:
        Resolved absolute Path.
    """
    if path is None:
        raise ValueError("Path cannot be None")

    path_obj = Path(path)

    if path_obj.is_absolute():
        return path_obj.resolve()

    base = base_dir if base_dir is not None else get_app_dir()
    return (base / path_obj).resolve()


def get_config_path(config_arg: Optional[str] = None) -> Path:
    """Get the configuration file path.

    Args:
        config_arg: Optional config path from command line argument.
            If None or just a filename (no directory component), uses configures directory.
            If an absolute or relative path with directory, resolves accordingly.

    Returns:
        Resolved absolute Path to the configuration file.
    """
    if config_arg is None:
        return get_configures_dir() / "config.toml"
    
    path_obj = Path(config_arg)
    if path_obj.is_absolute():
        return path_obj.resolve()
    
    if path_obj.parent == Path("."):
        return get_configures_dir() / path_obj.name
    
    return resolve_path(config_arg)


def get_env_path(env_arg: Optional[str] = None) -> Path:
    """Get the .env file path.

    Args:
        env_arg: Optional .env path from command line argument.
            If None or just a filename (no directory component), uses configures directory.
            If an absolute or relative path with directory, resolves accordingly.

    Returns:
        Resolved absolute Path to the .env file.
    """
    if env_arg is None:
        return get_configures_dir() / ".env"
    
    path_obj = Path(env_arg)
    if path_obj.is_absolute():
        return path_obj.resolve()
    
    if path_obj.parent == Path("."):
        return get_configures_dir() / path_obj.name
    
    return resolve_path(env_arg)


def get_prompt_path(prompt_arg: Optional[str] = None) -> Path:
    """Get the prompt template file path.

    Args:
        prompt_arg: Optional prompt file path.
            If None or just a filename (no directory component), uses configures directory.
            If an absolute or relative path with directory, resolves accordingly.

    Returns:
        Resolved absolute Path to the prompt file.
    """
    if prompt_arg is None:
        return get_configures_dir() / "analyze_prompt.md"
    
    path_obj = Path(prompt_arg)
    if path_obj.is_absolute():
        return path_obj.resolve()
    
    if path_obj.parent == Path("."):
        return get_configures_dir() / path_obj.name
    
    return resolve_path(prompt_arg)

"""Google Drive upload helper for receipt photos.

This module provides a placeholder for Google Drive integration.
When the MCP Google Drive server is authenticated, it can upload
receipt photos to a configurable folder.

For standalone usage without MCP, you can configure a local backup
folder in config.yaml instead.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

_BACKUP_DIR = Path(__file__).parent / "data" / "receipts_backup"


def upload_to_drive(photo_path: Path, drive_folder: str) -> Optional[str]:
    """Upload a receipt photo to Google Drive.

    Currently saves a local backup copy. To enable Google Drive upload,
    authenticate the MCP Google Drive server and extend this function.

    Returns the backup/drive path or URL.
    """
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = _BACKUP_DIR / photo_path.name
    shutil.copy2(photo_path, dest)
    return str(dest)

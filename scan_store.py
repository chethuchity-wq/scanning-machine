"""
Where each scan's images and values for the dashboard (scan_data) are kept.

They follow the report folder set in the dashboard's Settings:
<report folder>\\scan_data\\<orthanc study id>. With no report folder - or
when it can't be reached - they go in reports\\scan_data on this PC. Reading
looks in the report folder first, then on this PC, so scans saved before the
folder was set (or while it was unreachable) still show their images.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import config

LOCAL_ROOT = Path(config.OUTPUT_DIR) / "scan_data"


def _report_folder() -> str:
    from webapp import db
    try:
        return (db.get_clinic_info(db.get_default_clinic_id()).get("report_folder") or "").strip()
    except Exception:
        return ""


def _roots() -> list[Path]:
    folder = _report_folder()
    return ([Path(folder) / "scan_data"] if folder else []) + [LOCAL_ROOT]


def _safe(orthanc_study_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "", orthanc_study_id or "")


def find(orthanc_study_id: str) -> Path | None:
    """The scan's folder that has its data, or None."""
    name = _safe(orthanc_study_id)
    if not name:
        return None
    for root in _roots():
        try:
            if (root / name / "scan.json").exists():
                return root / name
        except OSError:
            continue
    return None


def target(orthanc_study_id: str) -> Path:
    """
    The folder to save the scan's data in (created): the report folder's
    scan_data when it can be written, else this PC's. A copy saved earlier
    in another place is removed, so each scan has one folder.
    """
    name = _safe(orthanc_study_id)
    chosen = None
    for root in _roots():
        try:
            (root / name).mkdir(parents=True, exist_ok=True)
            chosen = root / name
            break
        except OSError as e:
            print(f"  [SCAN DATA] Cannot use {root}: {e} - trying this PC")
    if chosen is None:
        raise OSError("No folder for the scan images")
    for root in _roots():
        other = root / name
        try:
            if other.resolve() != chosen.resolve() and other.exists():
                shutil.rmtree(other, ignore_errors=True)
        except OSError:
            pass
    return chosen


def move_local_to_report_folder() -> tuple[int, int]:
    """
    Move every scan's data from this PC into the report folder's scan_data
    (after the folder is set). Returns (moved, failed). Each folder is copied,
    checked, then deleted here.
    """
    folder = _report_folder()
    if not folder or not LOCAL_ROOT.exists():
        return 0, 0
    dest_root = Path(folder) / "scan_data"
    if dest_root.resolve() == LOCAL_ROOT.resolve():
        return 0, 0
    moved = failed = 0
    for src in sorted(p for p in LOCAL_ROOT.iterdir() if p.is_dir()):
        dest = dest_root / src.name
        try:
            if (dest / "scan.json").exists():
                shutil.rmtree(src)          # already there
                moved += 1
                continue
            shutil.copytree(src, dest, dirs_exist_ok=True)
            if sorted(f.name for f in src.iterdir()) != sorted(f.name for f in dest.iterdir()):
                raise OSError("copy incomplete")
            shutil.rmtree(src)
            moved += 1
        except OSError as e:
            print(f"  could not move {src.name}: {e}")
            failed += 1
    return moved, failed


if __name__ == "__main__":
    moved, failed = move_local_to_report_folder()
    print(f"Moved {moved} scan folder(s) to the report folder; {failed} failed")

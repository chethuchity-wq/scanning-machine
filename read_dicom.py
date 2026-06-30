"""
DICOM Measurement Reader
========================
Scans a folder of .dcm files (e.g. from USB export of a Philips ultrasound machine),
extracts all radiologist measurements from Structured Reports (SR) and image files,
and saves results to an Excel file.

Usage:
    python read_dicom.py --input "D:\\DICOM_Export" --output "measurements.xlsx"

    # Or just run it and it will prompt for the folder:
    python read_dicom.py
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

import pydicom
import pandas as pd

from extract_measurements import extract_from_sr, extract_from_image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODALITIES_WITH_MEASUREMENTS = {"SR", "US", "OT"}


def read_patient_info(ds) -> dict:
    """Pull standard patient / study identifiers from the dataset."""
    def safe(tag):
        val = ds.get(tag, None)
        return str(val.value).strip() if val is not None else ""

    study_date_raw = safe((0x0008, 0x0020))
    try:
        study_date = datetime.strptime(study_date_raw, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        study_date = study_date_raw

    return {
        "patient_name": safe((0x0010, 0x0010)),
        "patient_id":   safe((0x0010, 0x0020)),
        "dob":          safe((0x0010, 0x0030)),
        "study_date":   study_date,
        "accession_no": safe((0x0008, 0x0050)),
        "modality":     safe((0x0008, 0x0060)),
        "description":  safe((0x0008, 0x103E)),  # SeriesDescription
        "file":         "",  # filled in by caller
    }


def process_file(dcm_path: Path) -> list[dict]:
    """
    Read one .dcm file and return a flat list of rows ready for DataFrame.
    Each row = one measurement + patient context.
    """
    try:
        ds = pydicom.dcmread(str(dcm_path), force=True)
    except Exception as e:
        print(f"  [SKIP] Cannot read {dcm_path.name}: {e}")
        return []

    modality = str(ds.get((0x0008, 0x0060), "")).strip().upper()

    info = read_patient_info(ds)
    info["file"] = dcm_path.name

    # --- choose extraction strategy based on modality ---
    if modality == "SR":
        measurements = extract_from_sr(ds)
    elif modality in ("US", "OT", ""):
        measurements = extract_from_image(ds)
    else:
        measurements = extract_from_image(ds)  # try anyway

    if not measurements:
        return []

    rows = []
    for m in measurements:
        row = {**info, **m}
        rows.append(row)
    return rows


def scan_folder(folder: Path) -> list[dict]:
    """Walk a folder recursively and process every .dcm file found."""
    dcm_files = list(folder.rglob("*.dcm"))
    # Also try files with no extension (some exporters omit it)
    dcm_files += [f for f in folder.rglob("*") if f.is_file() and f.suffix == ""]

    if not dcm_files:
        print(f"No .dcm files found in: {folder}")
        return []

    print(f"Found {len(dcm_files)} DICOM file(s) — processing...\n")
    all_rows = []
    for i, path in enumerate(dcm_files, 1):
        print(f"  [{i}/{len(dcm_files)}] {path.name}")
        rows = process_file(path)
        all_rows.extend(rows)
        if rows:
            print(f"    → {len(rows)} measurement(s) found")

    return all_rows


def save_results(rows: list[dict], output_path: Path) -> None:
    """Save extracted measurements to an Excel file."""
    if not rows:
        print("\nNo measurements found in any file.")
        return

    df = pd.DataFrame(rows)

    # Reorder columns for readability
    preferred_order = [
        "patient_name", "patient_id", "dob", "study_date", "accession_no",
        "modality", "description", "measurement_name", "value", "unit",
        "context", "file",
    ]
    cols = [c for c in preferred_order if c in df.columns] + \
           [c for c in df.columns if c not in preferred_order]
    df = df[cols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Measurements")

        # Auto-size columns for readability
        worksheet = writer.sheets["Measurements"]
        for col_cells in worksheet.columns:
            max_len = max(
                len(str(cell.value)) if cell.value is not None else 0
                for cell in col_cells
            )
            worksheet.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 60)

    print(f"\nSaved {len(df)} measurement row(s) → {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract radiologist measurements from Philips DICOM files"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Path to folder containing .dcm files (e.g. USB drive)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="measurements.xlsx",
        help="Output Excel file path (default: measurements.xlsx)",
    )
    args = parser.parse_args()

    # If no input given, prompt the user interactively
    input_folder = args.input
    if not input_folder:
        input_folder = input("Enter path to DICOM folder (e.g. D:\\DICOM_Export): ").strip().strip('"')

    folder = Path(input_folder)
    if not folder.exists():
        print(f"ERROR: Folder not found: {folder}")
        sys.exit(1)

    output_path = Path(args.output)

    print(f"\nScanning: {folder}")
    print(f"Output:   {output_path}\n")
    print("-" * 50)

    rows = scan_folder(folder)
    save_results(rows, output_path)

    print("\nDone.")


if __name__ == "__main__":
    main()

"""
Ultrasound DICOM Reporting Pipeline
=====================================
Orchestrates the full workflow:
  1. Connect to Orthanc server (or read from local folder)
  2. Download/read DICOM files
  3. Extract measurements from SR (primary) + OCR (fallback)
  4. Evaluate against normal ranges
  5. Generate PDF report

Modes:
  - watch:  Poll Orthanc for new stable studies and auto-generate reports
  - study:  Process a specific study by Orthanc ID
  - folder: Process a local folder of DICOM files (like your existing read_dicom.py)
  - list:   List recent studies from Orthanc

Usage:
    # Watch mode — auto-process new studies
    python pipeline.py watch

    # Process a specific Orthanc study
    python pipeline.py study <orthanc-study-id>

    # Process a local folder
    python pipeline.py folder "D:\\DICOM_Export"

    # List recent studies on Orthanc
    python pipeline.py list

    # Search for a patient
    python pipeline.py search --name "Raj*" --date "20260601-20260630"
"""

import argparse
import io
import sys
from datetime import datetime
from pathlib import Path

import pydicom

import config
from orthanc_client import OrthancClient
from extract_measurements import extract_from_sr, extract_from_image
from ocr_extract import extract_measurements_ocr
from report_generator import generate_report
from scan_classifier import classify_scan, classify_scan_from_filename
import fill_report as _fill_report


# ---------------------------------------------------------------------------
# Core processing logic
# ---------------------------------------------------------------------------

def process_dataset(ds: pydicom.Dataset, filename: str = "") -> list[dict]:
    """
    Process a single DICOM dataset and extract all measurements.

    Strategy:
      1. If it's an SR — extract structured measurements (highest quality)
      2. If it's an image — try private tags first, then OCR as fallback
      3. Merge and deduplicate results

    Returns:
        List of measurement dicts with: measurement_name, value, unit, context
    """
    modality = str(ds.get((0x0008, 0x0060), "")).strip().upper()
    measurements = []

    # --- Strategy 1: Structured Report (best quality data) ---
    if modality == "SR":
        sr_measurements = extract_from_sr(ds)
        for m in sr_measurements:
            m["context"] = "SR"
        measurements.extend(sr_measurements)
        if measurements:
            return measurements  # SR data is definitive, no need for OCR

    # --- Strategy 2: Private tags / Ultrasound Region metadata ---
    image_measurements = extract_from_image(ds)
    for m in image_measurements:
        if "context" not in m or not m["context"]:
            m["context"] = "DICOM Tag"
    measurements.extend(image_measurements)

    # --- Strategy 3: OCR on pixel data (fallback) ---
    ocr_measurements = extract_measurements_ocr(ds)
    measurements.extend(ocr_measurements)

    # --- Deduplicate ---
    # If same measurement found via both methods, prefer the higher-confidence one
    measurements = _deduplicate_measurements(measurements)

    return measurements


def _deduplicate_measurements(measurements: list[dict]) -> list[dict]:
    """Remove duplicate measurements, preferring SR > DICOM Tag > OCR."""
    priority = {"SR": 3, "DICOM Tag": 2, "OCR": 1}
    seen = {}

    for m in measurements:
        # Skip pixel spacing / private tag entries that aren't clinical measurements
        name = m.get("measurement_name", "")
        if "pixel spacing" in name.lower() or "private" in name.lower():
            continue

        key = (name.lower().strip(), m.get("unit", "").lower())
        current_priority = priority.get(m.get("context", ""), 0)

        if key not in seen or current_priority > priority.get(seen[key].get("context", ""), 0):
            seen[key] = m

    return list(seen.values())


# ---------------------------------------------------------------------------
# Measurement name → fill_report data-dict field mapper
# ---------------------------------------------------------------------------

# Maps lower-cased measurement names (or substrings) to fill_report.py data keys.
# Checked in order; first match wins.
_MEASUREMENT_FIELD_MAP: list[tuple[str, str]] = [
    # Obstetric biometrics
    ("bi-parietal diameter", "bpd"),
    ("biparietal diameter", "bpd"),
    ("bpd", "bpd"),
    ("head circumference", "hc"),
    ("hc", "hc"),
    ("femur length", "fl"),
    ("femur", "fl"),
    ("fl", "fl"),
    ("abdominal circumference", "ac"),
    ("ac", "ac"),
    ("crown rump length", "crl"),
    ("crl", "crl"),
    ("nuchal translucency", "nt"),
    (" nt ", "nt"),
    ("nasal bone length", "nasal_bone_length"),
    ("nasal bone", "nasal_bone"),
    ("nuchal fold thickness", "nuchal_fold"),
    ("nuchal fold", "nuchal_fold"),
    ("humerus length", "hl"),
    ("humerus", "hl"),
    ("hl", "hl"),
    ("tibia length", "tl"),
    ("tibia", "tl"),
    ("tl", "tl"),
    ("radius length", "rl"),
    ("radius", "rl"),
    ("rl", "rl"),
    ("fibula", "fib"),
    ("ulna length", "ul"),
    ("ulna", "ul"),
    ("ul", "ul"),
    ("cerebellar diameter", "tcd"),
    ("tcd", "tcd"),
    ("cisterna magna", "cisterna_magna"),
    ("lateral ventricular atrium", "lvta"),
    ("foot length", "foot_length"),
    ("amniotic fluid index", "afi"),
    ("afi", "afi"),
    ("estimated foetal weight", "efw"),
    ("estimated fetal weight", "efw"),
    ("efw", "efw"),
    ("foetal heart rate", "fhr"),
    ("fetal heart rate", "fhr"),
    ("heart rate", "fhr"),
    ("fhr", "fhr"),
    # Abdomen
    ("liver span", "liver_size"),
    ("liver", "liver_size"),
    ("spleen length", "spleen_size"),
    ("spleen", "spleen_size"),
    ("right kidney", "right_kidney_size"),
    ("rt kidney", "right_kidney_size"),
    ("left kidney", "left_kidney_size"),
    ("lt kidney", "left_kidney_size"),
    ("uterus", "uterus_size"),
    ("endometrial thickness", "endometrium_mm"),
    ("endometrium", "endometrium_mm"),
    ("right ovary", "right_ovary_size"),
    ("rt ovary", "right_ovary_size"),
    ("left ovary", "left_ovary_size"),
    ("lt ovary", "left_ovary_size"),
    ("prostate", "prostate_notes"),
    # Doppler
    ("right uterine artery", "doppler_right_pi"),
    ("rt uterine artery", "doppler_right_pi"),
    ("left uterine artery", "doppler_left_pi"),
    ("lt uterine artery", "doppler_left_pi"),
    ("umbilical artery", "doppler_umbilical_pi"),
    ("middle cerebral artery", "doppler_mca_pi"),
    ("mca", "doppler_mca_pi"),
]


def _measurement_to_field(name: str) -> str | None:
    """Return the fill_report data key for a measurement name, or None."""
    norm = name.lower().strip()
    for fragment, field in _MEASUREMENT_FIELD_MAP:
        if fragment in norm:
            return field
    return None


def _build_docx_data(patient_info: dict, measurements: list[dict]) -> dict:
    """
    Build the data dict expected by fill_report.generate_report() from
    DICOM patient info and extracted measurements.
    """
    data: dict = {
        "patient_name": patient_info.get("patient_name", ""),
        "age": patient_info.get("age", ""),
        "date": patient_info.get("study_date", ""),
        "ref_by": patient_info.get("referring_physician", ""),
        # sex drives declaration pronoun: "F" → "her", "M" → "his"
        "_sex": patient_info.get("sex", "F"),
    }

    for m in measurements:
        field = _measurement_to_field(str(m.get("measurement_name", "")))
        if field and field not in data:
            val = m.get("value", "")
            data[field] = str(val) if val is not None else ""

    return data


def generate_docx_from_dicom(
    ds: pydicom.Dataset,
    measurements: list[dict],
    patient_info: dict,
    filename: str = "",
) -> Path | None:
    """
    Classify scan type from DICOM and generate the matching .docx report.

    Classification order:
      1. DICOM tags  (StudyDescription, ProtocolName, SeriesDescription)
      2. OCR text    (keywords burned into ultrasound image pixels)
      3. Measurements fingerprinting (which measurement names are present)
      4. Filename    (fallback for offline / local files)

    Returns:
        Path to generated .docx, or None if scan type cannot be determined.
    """
    # --- Classify ---
    scan_type, confidence, method = classify_scan(ds, measurements)

    # Fallback: try filename if DICOM/OCR/fingerprint returned nothing
    if scan_type == "unknown" and filename:
        scan_type, confidence, method = classify_scan_from_filename(filename)

    if scan_type == "unknown":
        print(f"  [DOCX] Cannot determine scan type – skipping .docx generation")
        return None

    print(f"  [DOCX] Scan type: {scan_type!r} (confidence {confidence:.0%}, method: {method})")

    # --- Build data dict ---
    data = _build_docx_data(patient_info, measurements)

    # --- Generate ---
    try:
        path = _fill_report.generate_report(scan_type, data)
        print(f"  [DOCX] Saved: {path}")
        return path
    except Exception as e:
        print(f"  [DOCX] Generation failed: {e}")
        return None


def extract_patient_info(ds: pydicom.Dataset) -> dict:
    """Extract patient and study info from DICOM dataset."""
    def safe(tag):
        val = ds.get(tag, None)
        return str(val.value).strip() if val is not None else ""

    study_date_raw = safe((0x0008, 0x0020))
    try:
        study_date = datetime.strptime(study_date_raw, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        study_date = study_date_raw

    dob_raw = safe((0x0010, 0x0030))
    try:
        dob = datetime.strptime(dob_raw, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        dob = dob_raw

    # PatientAge is stored as e.g. "024Y", "006M", "015D"
    age_raw = safe((0x0010, 0x1010))   # PatientAge
    if age_raw:
        age = age_raw.rstrip("YyMmDd").lstrip("0") or age_raw  # "024Y" → "24"
    elif dob_raw:
        # Derive age from birth date + study date
        try:
            birth = datetime.strptime(dob_raw, "%Y%m%d")
            study = datetime.strptime(study_date_raw, "%Y%m%d") if study_date_raw else datetime.today()
            age = str((study - birth).days // 365)
        except Exception:
            age = ""
    else:
        age = ""

    # PatientSex: "M", "F", or "O"
    sex = safe((0x0010, 0x0040)).upper()  # PatientSex

    return {
        "patient_name": safe((0x0010, 0x0010)).replace("^", " "),
        "patient_id": safe((0x0010, 0x0020)),
        "age": age,
        "sex": sex,            # "M" or "F"
        "dob": dob,
        "study_date": study_date,
        "accession_no": safe((0x0008, 0x0050)),
        "modality": safe((0x0008, 0x0060)),
        "description": safe((0x0008, 0x1030)) or safe((0x0008, 0x103E)),
        "referring_physician": safe((0x0008, 0x0090)).replace("^", " "),
        "institution": safe((0x0008, 0x0080)),
    }


# ---------------------------------------------------------------------------
# Pipeline modes
# ---------------------------------------------------------------------------

def process_orthanc_study(client: OrthancClient, study_id: str) -> Path:
    """
    Process a single study from Orthanc and generate a PDF report.

    Returns:
        Path to the generated PDF report
    """
    print(f"\n{'='*60}")
    print(f"Processing study: {study_id}")
    print(f"{'='*60}")

    # Get study info
    summary = client.get_study_summary(study_id)
    print(f"  Patient: {summary['patient_name']} ({summary['patient_id']})")
    print(f"  Date:    {summary['study_date']}")
    print(f"  Series:  {summary['series_count']} | Instances: {summary['instance_count']}")
    print(f"  Modalities: {', '.join(summary['modalities'])}")
    print()

    # Process all instances in the study
    all_measurements = []
    patient_info = None

    series_ids = client.list_series(study_id)
    for series_id in series_ids:
        series_info = client.get_series(series_id)
        modality = series_info.get("MainDicomTags", {}).get("Modality", "")
        print(f"  Series [{modality}]: {series_info.get('MainDicomTags', {}).get('SeriesDescription', 'N/A')}")

        instance_ids = client.list_instances(series_id)
        for instance_id in instance_ids:
            try:
                ds = client.get_instance_as_dataset(instance_id)

                # Get patient info from first dataset
                if patient_info is None:
                    patient_info = extract_patient_info(ds)

                # Extract measurements
                measurements = process_dataset(ds, filename=instance_id)
                if measurements:
                    print(f"    → {len(measurements)} measurement(s) from instance {instance_id[:8]}...")
                    all_measurements.extend(measurements)

            except Exception as e:
                print(f"    [ERROR] Instance {instance_id[:8]}: {e}")

    # Deduplicate across all instances
    all_measurements = _deduplicate_measurements(all_measurements)

    print(f"\n  Total measurements: {len(all_measurements)}")

    # Generate report
    if patient_info is None:
        patient_info = {
            "patient_name": summary["patient_name"],
            "patient_id": summary["patient_id"],
            "study_date": summary["study_date"],
        }

    report_path = generate_report(patient_info, all_measurements)
    print(f"  PDF report: {report_path}")

    # Also generate a .docx report (auto-detect scan type)
    # Use the last DICOM dataset for classification (SR or image)
    try:
        last_ds = client.get_instance_as_dataset(series_ids[-1]) if series_ids else None
        if last_ds is not None:
            generate_docx_from_dicom(last_ds, all_measurements, patient_info)
    except Exception as e:
        print(f"  [DOCX] Could not generate .docx: {e}")

    print(f"{'='*60}\n")
    return report_path


def process_local_folder(folder_path: str) -> Path:
    """
    Process a local folder of DICOM files and generate a PDF report.
    This is similar to your existing read_dicom.py but with the full pipeline.

    Returns:
        Path to the generated PDF report
    """
    folder = Path(folder_path)
    if not folder.exists():
        print(f"ERROR: Folder not found: {folder}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Processing folder: {folder}")
    print(f"{'='*60}")

    # Find DICOM files
    dcm_files = list(folder.rglob("*.dcm"))
    dcm_files += [f for f in folder.rglob("*") if f.is_file() and f.suffix == ""]

    if not dcm_files:
        print(f"No DICOM files found in: {folder}")
        sys.exit(1)

    print(f"  Found {len(dcm_files)} DICOM file(s)\n")

    all_measurements = []
    patient_info = None

    for i, dcm_path in enumerate(dcm_files, 1):
        try:
            ds = pydicom.dcmread(str(dcm_path), force=True)
        except Exception as e:
            print(f"  [{i}] SKIP {dcm_path.name}: {e}")
            continue

        # Get patient info from first readable file
        if patient_info is None:
            patient_info = extract_patient_info(ds)

        # Extract measurements
        measurements = process_dataset(ds, filename=dcm_path.name)
        if measurements:
            print(f"  [{i}] {dcm_path.name} → {len(measurements)} measurement(s)")
            all_measurements.extend(measurements)
        else:
            print(f"  [{i}] {dcm_path.name} → no measurements")

    # Deduplicate
    all_measurements = _deduplicate_measurements(all_measurements)

    print(f"\n  Total measurements: {len(all_measurements)}")

    if patient_info is None:
        patient_info = {
            "patient_name": "Unknown",
            "patient_id": "",
            "study_date": datetime.now().strftime("%Y-%m-%d"),
        }

    # Generate PDF report
    report_path = generate_report(patient_info, all_measurements)
    print(f"\n  PDF report: {report_path}")

    # Also generate a .docx report (auto-detect scan type from first DICOM file)
    try:
        first_ds = pydicom.dcmread(str(dcm_files[0]), force=True)
        generate_docx_from_dicom(
            first_ds, all_measurements, patient_info,
            filename=dcm_files[0].name,
        )
    except Exception as e:
        print(f"  [DOCX] Could not generate .docx: {e}")

    print(f"{'='*60}\n")
    return report_path


def watch_orthanc():
    """
    Watch Orthanc for new stable studies and auto-generate reports.
    Runs indefinitely until Ctrl+C.
    """
    client = OrthancClient()

    # Test connection first
    try:
        info = client.test_connection()
        print(f"Connected to Orthanc {info.get('Version', '?')} at {config.ORTHANC_URL}")
        print(f"DICOM AET: {info.get('DicomAet', '?')}")
    except Exception as e:
        print(f"ERROR: Cannot connect to Orthanc at {config.ORTHANC_URL}: {e}")
        print("Check config.py ORTHANC_URL, ORTHANC_USERNAME, ORTHANC_PASSWORD")
        sys.exit(1)

    print(f"\nReport output directory: {config.OUTPUT_DIR}")
    print(f"Poll interval: {config.POLL_INTERVAL_SECONDS}s")
    print("-" * 60)

    def on_stable_study(study_id: str, study_info: dict):
        """Callback for new stable studies."""
        try:
            report_path = process_orthanc_study(client, study_id)
            print(f"  ✓ Report ready: {report_path}")
        except Exception as e:
            print(f"  ✗ Failed to process study {study_id}: {e}")

    # Start watching
    client.watch_for_stable_studies(callback=on_stable_study)


def list_recent_studies(limit: int = 20):
    """List recent studies from Orthanc."""
    client = OrthancClient()

    try:
        client.test_connection()
    except Exception as e:
        print(f"ERROR: Cannot connect to Orthanc: {e}")
        sys.exit(1)

    study_ids = client.list_studies()
    print(f"\nFound {len(study_ids)} studies on Orthanc server")
    print(f"Showing last {min(limit, len(study_ids))}:\n")

    print(f"{'ID':<20} {'Patient':<25} {'Date':<12} {'Modalities':<10} {'Description'}")
    print("-" * 90)

    for study_id in study_ids[-limit:]:
        try:
            summary = client.get_study_summary(study_id)
            print(
                f"{study_id[:18]:<20} "
                f"{summary['patient_name'][:23]:<25} "
                f"{summary['study_date']:<12} "
                f"{','.join(summary['modalities']):<10} "
                f"{summary['study_description'][:30]}"
            )
        except Exception as e:
            print(f"{study_id[:18]:<20} [Error: {e}]")


def search_studies(patient_name: str = None, patient_id: str = None, study_date: str = None):
    """Search for studies on Orthanc."""
    client = OrthancClient()

    try:
        client.test_connection()
    except Exception as e:
        print(f"ERROR: Cannot connect to Orthanc: {e}")
        sys.exit(1)

    print(f"\nSearching Orthanc...")
    results = client.find_studies(
        patient_name=patient_name,
        patient_id=patient_id,
        study_date=study_date,
        modality="US",
    )

    if not results:
        print("No matching studies found.")
        return

    print(f"Found {len(results)} matching study/studies:\n")
    for study in results:
        main_tags = study.get("MainDicomTags", {})
        patient_tags = study.get("PatientMainDicomTags", {})
        print(f"  ID:      {study.get('ID', '?')}")
        print(f"  Patient: {patient_tags.get('PatientName', '?')}")
        print(f"  Date:    {main_tags.get('StudyDate', '?')}")
        print(f"  Desc:    {main_tags.get('StudyDescription', '-')}")
        print()


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ultrasound DICOM Reporting Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py watch                          # Auto-process new studies from Orthanc
  python pipeline.py study abc123-def456            # Process specific study
  python pipeline.py folder "D:\\DICOM_Export"       # Process local DICOM folder
  python pipeline.py list                           # List recent studies
  python pipeline.py search --name "Kumar*"         # Search by patient name
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Pipeline mode")

    # Watch mode
    watch_parser = subparsers.add_parser("watch", help="Watch Orthanc for new studies")

    # Process specific study
    study_parser = subparsers.add_parser("study", help="Process a specific Orthanc study")
    study_parser.add_argument("study_id", type=str, help="Orthanc study ID")

    # Process local folder
    folder_parser = subparsers.add_parser("folder", help="Process local DICOM folder")
    folder_parser.add_argument("path", type=str, help="Path to DICOM folder")
    folder_parser.add_argument("--output", "-o", type=str, default=None, help="Output PDF path")

    # List studies
    list_parser = subparsers.add_parser("list", help="List recent studies from Orthanc")
    list_parser.add_argument("--limit", "-n", type=int, default=20, help="Number of studies to show")

    # Search
    search_parser = subparsers.add_parser("search", help="Search for studies")
    search_parser.add_argument("--name", type=str, help="Patient name (supports wildcards)")
    search_parser.add_argument("--id", type=str, help="Patient ID")
    search_parser.add_argument("--date", type=str, help="Study date (YYYYMMDD or range YYYYMMDD-YYYYMMDD)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    print(f"\n{'='*60}")
    print(f"  Ultrasound DICOM Reporting Pipeline")
    print(f"  {config.CLINIC_NAME}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    if args.command == "watch":
        watch_orthanc()
    elif args.command == "study":
        client = OrthancClient()
        process_orthanc_study(client, args.study_id)
    elif args.command == "folder":
        process_local_folder(args.path)
    elif args.command == "list":
        list_recent_studies(limit=args.limit)
    elif args.command == "search":
        search_studies(
            patient_name=args.name,
            patient_id=args.id,
            study_date=args.date,
        )


if __name__ == "__main__":
    main()

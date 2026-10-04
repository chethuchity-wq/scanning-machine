"""
Scan Type Classifier
=====================
Automatically identifies which ultrasound report type to generate
from a DICOM file, using these layers (tried in order):

  Layer 0 – Exam type   : exam and preset chosen on the scanner (+ GA for OB)
  Layer 1 – DICOM tags  : StudyDescription / SeriesDescription / ProtocolName
  Layer 2 – OCR text    : Keywords burned into the ultrasound image screen
  Layer 3 – Measurements: Which measurement names are present (fingerprinting)

Returns one of the fill_report.py scan type keys:
    early_pregnancy | nt_scan | anomaly_scan | growth_scan |
    follicular_study | abdomen_pelvis_female | abdomen_pelvis_male

Usage:
    from scan_classifier import classify_scan
    import pydicom

    ds = pydicom.dcmread("scan.dcm")
    scan_type, confidence, method = classify_scan(ds)
    # e.g. ("nt_scan", 0.95, "dicom_tag")
"""

from __future__ import annotations

import re
from typing import Optional

import pydicom
from pydicom.dataset import Dataset

# ---------------------------------------------------------------------------
# Keyword rules – checked in the order listed; first match wins within a layer
# ---------------------------------------------------------------------------

# Each entry: (scan_type_key, [list of phrases to match])
# Phrases are matched case-insensitively anywhere in the text.
KEYWORD_RULES: list[tuple[str, list[str]]] = [
    # Most specific first
    ("nt_scan", [
        "nt scan", "nuchal translucency", "nt measurement", "nt+nb",
        "nt &", "first trimester nt", "nt -", "11-14 weeks",
    ]),
    ("early_pregnancy", [
        "early pregnancy", "dating scan", "viability scan", "first trimester scan",
        "early preg", "6-10 weeks", "ep scan", "early obs scan",
    ]),
    ("anomaly_scan", [
        "anomaly scan", "morphology scan", "anatomy scan", "tiffa",
        "level 2 scan", "anomalous scan", "mid trimester", "fetal anomaly",
        "anomaly", "20-24 weeks",
    ]),
    ("growth_scan", [
        "growth scan", "growth assessment", "biophysical profile", "bpp scan",
        "third trimester scan", "fetal growth", "foetal growth",
        "growth and wellbeing", "growth & doppler",
    ]),
    ("follicular_study", [
        "follicular study", "follicular monitoring", "follicle study",
        "follicular scan", "pcos", "iui monitoring", "ivf monitoring",
        "ovarian monitoring", "follicle monitoring", "antral follicle",
    ]),
    # Abdomen – check male-specific terms before generic pelvis
    ("abdomen_pelvis_male", [
        "male abdomen", "scrotal scan", "prostate scan", "scrotum",
        "testicular", "usg abdomen male",
    ]),
    ("abdomen_pelvis_female", [
        "abdomino-pelvic", "abdomen pelvis", "abdominal pelvis",
        "pelvic scan", "usg abdomen pelvis", "usg pelvis",
        "usg abdomen & pelvis", "usg abdomen and pelvis",
    ]),
    # Generic obstetric – less specific, checked last
    ("growth_scan", [
        "obstetric scan", "obstetric ultrasound", "3rd trimester",
    ]),
    ("nt_scan", [
        "first trimester",
    ]),
]

# ---------------------------------------------------------------------------
# Measurement fingerprinting rules
# ---------------------------------------------------------------------------
# Each entry: (scan_type_key, required_keywords, bonus_keywords)
# required: at least ONE of these measurement names must be present
# bonus:    each additional bonus keyword increases the score

FINGERPRINT_RULES: list[tuple[str, list[str], list[str]]] = [
    ("follicular_study", ["endometrial thickness", "antral follicle", "follicle"], [
        "right ovary", "left ovary",
    ]),
    ("nt_scan", ["nuchal translucency", "nt"], [
        "crl", "nasal bone", "ductus venosus",
    ]),
    ("early_pregnancy", ["crl", "crown rump length"], [
        "gestational sac", "cardiac activity", "fetal heart rate", "yolk sac",
    ]),
    ("anomaly_scan", ["nuchal fold", "nasal bone length", "tcd", "cisterna magna",
                      "lateral ventricular atrium"], [
        "bpd", "hc", "fl", "ac", "hl", "tl",
    ]),
    ("growth_scan", ["afi", "amniotic fluid index", "biophysical"], [
        "bpd", "hc", "fl", "ac", "efw",
    ]),
    # Abdomen fingerprint: presence of organ names without foetal measurements
    ("abdomen_pelvis_female", ["liver", "spleen", "gallbladder"], [
        "kidney", "uterus", "ovary",
    ]),
    ("abdomen_pelvis_male", ["liver", "spleen", "gallbladder"], [
        "kidney", "prostate", "bladder",
    ]),
]

# ---------------------------------------------------------------------------
# DICOM tags that describe the study type
# ---------------------------------------------------------------------------
DESCRIPTION_TAGS = [
    (0x0008, 0x1030),   # StudyDescription
    (0x0018, 0x1030),   # ProtocolName
    (0x0008, 0x103E),   # SeriesDescription
    (0x0008, 0x0068),   # PresentationIntentType
    (0x0040, 0x0007),   # ScheduledProcedureStepDescription
    (0x0032, 0x1070),   # RequestedContrastAgent (sometimes misused for protocol)
    (0x0010, 0x21B0),   # AdditionalPatientHistory (sometimes has scan type)
]

# ---------------------------------------------------------------------------
# Exam type chosen on the scanner (Philips Affiniti)
# ---------------------------------------------------------------------------
# The exam picked at the start of a scan is sent in every image and SR as
# CommentsOnThePerformedProcedureStep ("OB", "Abdomen"); the imaging preset
# as ProcessingFunction ("OB_GENERAL", "ABD_RENAL", "GYN_FERTILITY", ...).
# ProtocolName is always "Free Form" and says nothing.
EXAM_TYPE_TAG = (0x0040, 0x0280)        # CommentsOnThePerformedProcedureStep
PRESET_TAG = (0x0018, 0x5020)           # ProcessingFunction

# Obstetric form by gestational age: (below this many weeks, form)
OB_FORM_BY_GA_WEEKS = [
    (11, "early_pregnancy"),
    (14, "nt_scan"),
    (28, "anomaly_scan"),
    (99, "growth_scan"),
]
OB_SCAN_TYPES = {"early_pregnancy", "nt_scan", "anomaly_scan", "growth_scan"}

# Measurements that give the gestational age, best first
_GA_MEASUREMENTS = ("composite ultrasound age", "gestational age", "gestational age by lmp")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace for consistent matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _match_keywords(text: str) -> Optional[tuple[str, float]]:
    """
    Try every keyword rule against `text`.
    Returns (scan_type, confidence) for the first match, or None.
    """
    norm = _normalise(text)
    for scan_type, phrases in KEYWORD_RULES:
        for phrase in phrases:
            if phrase in norm:
                return scan_type, 0.95
    return None


# Derived values (percentiles, z-scores, ratios) name the statistic, not a
# measurement taken - "Growth Percentile Rank" is not evidence of anything.
_DERIVED_NAME_RE = re.compile(r"\b(ratio|percentile|centile|z[- ]?score|rank)\b")


def _keyword_pattern(keyword: str) -> re.Pattern:
    """
    Match a fingerprint keyword at a word start. Short abbreviations must also
    end on a word boundary: plain substring matching let "nt" hit inside
    "Growth Percentile Rank" and classify an 8-week early pregnancy as an NT
    scan. Longer keywords stay prefix matches so "follicle" still finds
    "Follicles".
    """
    tail = r"\b" if len(keyword) <= 3 else ""
    return re.compile(r"\b" + re.escape(keyword) + tail)


def _fingerprint_measurements(measurement_names: list[str]) -> Optional[tuple[str, float]]:
    """
    Score each scan type based on which measurement labels are present.
    Returns (best_scan_type, confidence) or None if no clear winner.
    """
    norm_names = [
        n for n in (_normalise(n) for n in measurement_names)
        if not _DERIVED_NAME_RE.search(n)
    ]

    def present(keyword: str) -> bool:
        pattern = _keyword_pattern(keyword)
        return any(pattern.search(name) for name in norm_names)

    scores: dict[str, float] = {}
    for scan_type, required, bonus in FINGERPRINT_RULES:
        # Must match at least one required keyword
        required_hits = sum(1 for req in required if present(req))
        if required_hits == 0:
            continue

        bonus_hits = sum(1 for b in bonus if present(b))
        score = required_hits * 2 + bonus_hits
        scores[scan_type] = max(scores.get(scan_type, 0), score)

    if not scores:
        return None

    best = max(scores, key=lambda k: scores[k])
    best_score = scores[best]

    # Normalise to 0–1 confidence (cap at 0.85 since fingerprinting is heuristic)
    max_possible = 10
    confidence = min(best_score / max_possible, 0.85)

    # Require a minimum score to avoid weak guesses
    if confidence < 0.2:
        return None

    return best, confidence


# ---------------------------------------------------------------------------
# Layer 0: exam type chosen on the scanner
# ---------------------------------------------------------------------------

def _tag_text(ds: Dataset, tag: tuple[int, int]) -> str:
    element = ds.get(tag)
    return str(element.value).strip().upper() if element is not None else ""


def _gestational_weeks(measurements: list[dict]) -> Optional[float]:
    """Gestational age in weeks from the scanner's measurements, if any."""
    by_name = {}
    for m in measurements:
        by_name.setdefault(_normalise(str(m.get("measurement_name", ""))), m)
    for name in _GA_MEASUREMENTS:
        m = by_name.get(name)
        if m is None:
            continue
        unit = _normalise(str(m.get("unit", "")))
        try:
            value = float(m.get("value"))
        except (TypeError, ValueError):
            continue
        if unit in ("d", "day", "days"):
            return value / 7
        if unit in ("wk", "wks", "week", "weeks"):
            return value
    return _weeks_from_biometry(by_name)


# Hadlock: gestational age (weeks) from a single biometry value in cm. Only
# picks the report form when the scanner sent no GA (no SR, values read from
# the image) - accurate to a week or two, plenty for that.
_HADLOCK = {
    "femur length": lambda cm: 10.35 + 2.460 * cm + 0.170 * cm ** 2,
    "fl": lambda cm: 10.35 + 2.460 * cm + 0.170 * cm ** 2,
    "biparietal diameter": lambda cm: 9.54 + 1.482 * cm + 0.1676 * cm ** 2,
    "bpd": lambda cm: 9.54 + 1.482 * cm + 0.1676 * cm ** 2,
}


def _weeks_from_biometry(by_name: dict[str, dict]) -> Optional[float]:
    for name, formula in _HADLOCK.items():
        m = by_name.get(name)
        if m is None:
            continue
        unit = _normalise(str(m.get("unit", "")))
        try:
            value = float(m.get("value"))
        except (TypeError, ValueError):
            continue
        cm = {"cm": value, "mm": value / 10}.get(unit)
        if cm and 0.5 <= cm <= 12:
            return formula(cm)
    return None


def _classify_from_exam(ds: Dataset, measurements: list[dict]) -> Optional[tuple[str, float, str]]:
    """
    Use the exam type and preset chosen on the scanner. These say which body
    region was scanned; for an obstetric exam the form is then chosen by
    gestational age, or failing that by which measurements were taken.
    Returns None when the exam type is missing or the form can't be decided.
    """
    exam = _tag_text(ds, EXAM_TYPE_TAG)
    preset = _tag_text(ds, PRESET_TAG)

    # Breast / small-parts breast preset (e.g. "BREAST", "SMP_BREAST")
    if exam == "BREAST" or "BREAST" in preset:
        return "breast_scan", 0.90, f"exam:{exam or preset}"
    if preset == "GYN_FERTILITY":
        return "follicular_study", 0.90, "exam:GYN_FERTILITY"
    if preset.startswith("GYN"):
        return "abdomen_pelvis_female", 0.90, f"exam:{preset}"

    if exam == "ABDOMEN":
        return _abdomen_by_sex(ds, 0.90, "exam:Abdomen")

    if exam == "OB":
        weeks = _gestational_weeks(measurements)
        if weeks is not None:
            for limit, scan_type in OB_FORM_BY_GA_WEEKS:
                if weeks < limit:
                    return scan_type, 0.90, f"exam:OB, GA {weeks:.1f} weeks"
        fp = _fingerprint_measurements([str(m.get("measurement_name", "")) for m in measurements])
        if fp and fp[0] in OB_SCAN_TYPES:
            return fp[0], 0.80, "exam:OB + measurements"
        # Exam left on OB from the previous patient but scanned on an abdomen
        # preset, with no foetal measurements: trust the preset, flagged
        if preset.startswith("ABD"):
            return _abdomen_by_sex(ds, 0.45, f"exam:OB but preset {preset}")
    return None


def _abdomen_by_sex(ds: Dataset, confidence: float, method: str) -> tuple[str, float, str]:
    """Abdomen & pelvis form for the patient's sex; female, flagged, if not entered."""
    sex = _tag_text(ds, (0x0010, 0x0040))  # PatientSex
    if sex == "M":
        return "abdomen_pelvis_male", confidence, method
    if sex == "F":
        return "abdomen_pelvis_female", confidence, method
    return "abdomen_pelvis_female", min(confidence, 0.45), method + " (sex not entered)"


# ---------------------------------------------------------------------------
# Layer 1: DICOM tag classification
# ---------------------------------------------------------------------------

def _classify_from_tags(ds: Dataset) -> Optional[tuple[str, float, str]]:
    """
    Check DICOM metadata tags for study/protocol descriptions.
    Returns (scan_type, confidence, "dicom_tag") or None.
    """
    for tag in DESCRIPTION_TAGS:
        raw = ds.get(tag, None)
        if raw is None:
            continue
        text = str(raw.value).strip() if hasattr(raw, "value") else str(raw).strip()
        if not text or text in ("-", "N/A", "None", ""):
            continue
        match = _match_keywords(text)
        if match:
            scan_type, conf = match
            return scan_type, conf, f"dicom_tag:{hex(tag[0])},{hex(tag[1])}"

    return None


# ---------------------------------------------------------------------------
# Layer 2: OCR text classification
# ---------------------------------------------------------------------------

def _classify_from_ocr(ds: Dataset) -> Optional[tuple[str, float, str]]:
    """
    Run OCR on the DICOM image and scan the full extracted text for keywords.
    Returns (scan_type, confidence, "ocr") or None.

    This relies on the existing ocr_extract infrastructure.
    """
    try:
        from ocr_extract import extract_measurements_ocr
        from PIL import Image, ImageOps
        import numpy as np
    except ImportError:
        return None

    # Get pixel array
    try:
        pixel_array = ds.pixel_array
    except Exception:
        return None

    # Convert to PIL image
    try:
        if len(pixel_array.shape) == 3 and pixel_array.shape[2] == 3:
            img = Image.fromarray(pixel_array, mode="RGB")
        elif len(pixel_array.shape) == 2:
            img = Image.fromarray(pixel_array, mode="L")
        else:
            img = Image.fromarray(pixel_array[:, :, 0], mode="L")
    except Exception:
        return None

    # OCR the full image (not just measurement regions — we want header text too)
    try:
        import pytesseract
        import config
        if config.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

        # Preprocess: invert (white text on dark background → dark on light)
        gray = img.convert("L")
        inverted = ImageOps.invert(gray)

        full_text = pytesseract.image_to_string(inverted, config="--psm 6")
    except Exception:
        return None

    if not full_text.strip():
        return None

    match = _match_keywords(full_text)
    if match:
        scan_type, conf = match
        # Slightly lower confidence than DICOM tag (OCR can misread)
        return scan_type, conf * 0.90, "ocr"

    return None


# ---------------------------------------------------------------------------
# Layer 3: Measurement fingerprinting
# ---------------------------------------------------------------------------

def _classify_from_measurements(measurements: list[dict]) -> Optional[tuple[str, float, str]]:
    """
    Infer scan type from which measurement names are present in the extracted data.
    Returns (scan_type, confidence, "fingerprint") or None.
    """
    if not measurements:
        return None

    names = [str(m.get("measurement_name", "")) for m in measurements]
    result = _fingerprint_measurements(names)
    if result:
        scan_type, conf = result
        return scan_type, conf, "fingerprint"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_scan(
    ds: Dataset,
    measurements: Optional[list[dict]] = None,
) -> tuple[str, float, str]:
    """
    Classify the ultrasound scan type from a DICOM dataset.

    Args:
        ds:           pydicom Dataset (already loaded).
        measurements: Pre-extracted measurements list (optional). If not provided,
                      fingerprinting layer is skipped unless measurements can be
                      extracted internally.

    Returns:
        (scan_type, confidence, method)
        scan_type  – key for fill_report.SCAN_GENERATORS, or "unknown"
        confidence – 0.0–1.0
        method     – "dicom_tag" | "ocr" | "fingerprint" | "unknown"

    Example:
        >>> ds = pydicom.dcmread("nt_scan.dcm")
        >>> classify_scan(ds)
        ("nt_scan", 0.95, "dicom_tag:0x8,0x1030")
    """
    # Layer 0: exam type chosen on the scanner. Even an uncertain answer here
    # (abdomen exam, sex not entered) beats guessing from the other layers.
    exam_result = _classify_from_exam(ds, measurements or [])
    if exam_result:
        return exam_result

    # Layer 1: DICOM metadata tags (fastest, most reliable)
    result = _classify_from_tags(ds)
    if result and result[1] >= 0.80:
        return result

    # Layer 2: OCR on image pixels
    ocr_result = _classify_from_ocr(ds)
    if ocr_result and ocr_result[1] >= 0.70:
        # If Layer 1 also had a low-confidence result, prefer whichever is higher
        if result is None or ocr_result[1] > result[1]:
            return ocr_result

    # Layer 3: Measurement fingerprinting
    if measurements is None:
        # Try to extract measurements now so we can fingerprint them
        try:
            from extract_measurements import extract_from_sr, extract_from_image
            modality = str(ds.get("Modality", "")).strip().upper()
            measurements = extract_from_sr(ds) if modality == "SR" else extract_from_image(ds)
        except Exception:
            measurements = []

    fp_result = _classify_from_measurements(measurements or [])
    if fp_result:
        if result is None or fp_result[1] > result[1]:
            return fp_result

    # Return whatever we have, even if low confidence
    if result:
        return result
    if ocr_result:
        return ocr_result

    return "unknown", 0.0, "unknown"


def classify_scan_from_text(text: str) -> tuple[str, float, str]:
    """
    Classify scan type from free text (e.g. referral note, report header, filename).
    Useful for classifying existing .docx files or typed study descriptions.

    Args:
        text: Any free text string.

    Returns:
        (scan_type, confidence, "text_match") or ("unknown", 0.0, "unknown")
    """
    match = _match_keywords(text)
    if match:
        return match[0], match[1], "text_match"
    return "unknown", 0.0, "unknown"


def classify_scan_from_filename(filename: str) -> tuple[str, float, str]:
    """
    Guess scan type from a filename (e.g. 'D.Latha nt scan.docx').

    Returns:
        (scan_type, confidence, "filename") or ("unknown", 0.0, "unknown")
    """
    # Remove extension and patient name noise — look for scan type words
    stem = re.sub(r"\.[a-z]{2,5}$", "", filename, flags=re.IGNORECASE)
    match = _match_keywords(stem)
    if match:
        return match[0], match[1] * 0.80, "filename"  # slightly lower confidence
    return "unknown", 0.0, "unknown"


# ---------------------------------------------------------------------------
# Demo / test when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=== Scan Classifier – Text Demo ===\n")

    test_cases = [
        # (input_text, expected_type)
        ("NT SCAN – First Trimester Assessment", "nt_scan"),
        ("Early Pregnancy Scan", "early_pregnancy"),
        ("TIFFA / Anomaly Scan 20 weeks", "anomaly_scan"),
        ("Growth Assessment and Biophysical Profile", "growth_scan"),
        ("PELVIC ULTRASOUND REPORT (FOLLICULAR STUDY)", "follicular_study"),
        ("ABDOMINO-PELVIC ULTRASOUND REPORT", "abdomen_pelvis_female"),
        ("D.Latha nt scan.docx", "nt_scan"),
        ("Kalaiselvi mani anomaly scan.docx", "anomaly_scan"),
        ("vidya shree early preg.docx", "early_pregnancy"),
        ("Chaithra follicular study.docx", "follicular_study"),
        ("Shwetha.K.N. growth scan.docx", "growth_scan"),
    ]

    all_pass = True
    for text, expected in test_cases:
        scan_type, conf, method = classify_scan_from_text(text)
        # Also try filename classification for .docx entries
        if scan_type == "unknown" and text.endswith(".docx"):
            scan_type, conf, method = classify_scan_from_filename(text)

        status = "✓" if scan_type == expected else "✗"
        if scan_type != expected:
            all_pass = False
        print(f"  {status}  [{method:12s}] {conf:.2f}  '{text}'")
        print(f"       → got: {scan_type}   expected: {expected}\n")

    print("All tests passed." if all_pass else "Some tests FAILED.")

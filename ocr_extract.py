"""
OCR Measurement Extractor for Ultrasound Images
=================================================
Extracts burned-in text annotations from ultrasound DICOM images.
Philips (and most) ultrasound machines overlay measurement results
directly on the image pixels. This module reads that text using OCR.

Usage:
    from ocr_extract import extract_measurements_ocr

    ds = pydicom.dcmread("ultrasound.dcm")
    measurements = extract_measurements_ocr(ds)
    # [{"measurement_name": "Liver", "value": 14.2, "unit": "cm", "context": "OCR", "confidence": 87}]
"""

import re
from typing import Optional

import numpy as np
import pydicom
from pydicom.dataset import Dataset

try:
    from PIL import Image, ImageFilter, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

import config

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

if HAS_TESSERACT and config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

# ---------------------------------------------------------------------------
# Measurement Patterns
# ---------------------------------------------------------------------------

# Common ultrasound measurement patterns found burned into images
# Format: (regex_pattern, measurement_name_group, value_group, unit_group)
MEASUREMENT_PATTERNS = [
    # Standard format: "Label: 12.3 cm" or "Label  12.3cm"
    r"(?P<name>[A-Za-z][A-Za-z\s\.\-/]{1,30}?)[\s:=]+(?P<value>\d+\.?\d*)\s*(?P<unit>cm|mm|ml|cc|m/s|cm/s|mmHg|%|bpm)",
    # Format with parentheses: "Liver (span): 14.2 cm"
    r"(?P<name>[A-Za-z][A-Za-z\s\.\-/()]{1,35}?)[\s:=]+(?P<value>\d+\.?\d*)\s*(?P<unit>cm|mm|ml|cc|m/s|cm/s|mmHg|%|bpm)",
    # Dist/Length format: "Dist 1: 14.23cm" or "D1= 3.45cm"
    r"(?P<name>(?:Dist|D|Length|L|Vol|Area|Circ)\s*\d*)[\s:=]+(?P<value>\d+\.?\d*)\s*(?P<unit>cm|mm|ml|cc|cm2|cm3)",
    # Velocity format: "Vmax: 1.23 m/s" or "PSV 45.6 cm/s"
    r"(?P<name>(?:Vmax|Vmin|PSV|EDV|RI|PI|S/D|TAV|TAMV))\s*[:=]?\s*(?P<value>\d+\.?\d*)\s*(?P<unit>m/s|cm/s|mmHg|%)?",
    # Volume format: "Vol: 123.4 ml"
    r"(?P<name>(?:Vol|Volume))\s*[:=]?\s*(?P<value>\d+\.?\d*)\s*(?P<unit>ml|cc|cm3)?",
    # EF/FS format: "EF: 65%" or "FS: 35%"
    r"(?P<name>(?:EF|FS|FAC))\s*[:=]?\s*(?P<value>\d+\.?\d*)\s*(?P<unit>%)?",
]

# Known ultrasound measurement labels (helps disambiguate OCR noise)
KNOWN_LABELS = {
    # Abdomen
    "liver", "liver span", "liver length", "rt lobe", "lt lobe", "caudate",
    "spleen", "spleen length", "splenic length",
    "kidney", "rt kidney", "lt kidney", "right kidney", "left kidney",
    "kidney length", "renal length", "cortex",
    "cbd", "common bile duct", "portal vein", "pv", "hepatic vein",
    "aorta", "ivc", "pancreas", "gallbladder", "gb wall",
    # Obstetric
    "bpd", "hc", "ac", "fl", "crl", "nt", "efw",
    "afi", "amniotic fluid",
    # Cardiac
    "ef", "fs", "lv", "rv", "la", "ra", "ivs", "lvpw",
    "aov", "mv", "tv", "pv",
    "psv", "edv", "ri", "pi", "s/d",
    # Thyroid
    "thyroid", "rt thyroid", "lt thyroid", "isthmus", "nodule",
    # Measurements
    "dist", "length", "width", "height", "depth", "area", "vol", "volume",
    "circumference", "circ", "diameter", "diam",
}

# Compile patterns
COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in MEASUREMENT_PATTERNS]


# ---------------------------------------------------------------------------
# Image Processing
# ---------------------------------------------------------------------------

def _pixel_array_to_image(ds: Dataset) -> Optional[Image.Image]:
    """Convert DICOM pixel data to PIL Image."""
    if not HAS_PIL:
        return None

    try:
        pixel_array = ds.pixel_array
    except Exception:
        return None

    # Handle different pixel array shapes
    if len(pixel_array.shape) == 3:
        # Color image (RGB or YBR)
        if pixel_array.shape[2] == 3:
            img = Image.fromarray(pixel_array, mode="RGB")
        else:
            img = Image.fromarray(pixel_array[:, :, 0], mode="L")
    elif len(pixel_array.shape) == 2:
        # Grayscale
        img = Image.fromarray(pixel_array, mode="L")
    else:
        return None

    return img


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """
    Preprocess ultrasound image for better OCR accuracy.
    Ultrasound annotations are typically white/bright text on dark background.
    """
    # Convert to grayscale if color
    if img.mode != "L":
        img = img.convert("L")

    # Invert (OCR works better with dark text on light background)
    img = ImageOps.invert(img)

    # Increase contrast — threshold to make text sharper
    threshold = 180
    img = img.point(lambda x: 255 if x > threshold else 0, mode="L")

    # Slight sharpen
    img = img.filter(ImageFilter.SHARPEN)

    return img


def _crop_region(img: Image.Image, region: tuple[float, float, float, float]) -> Image.Image:
    """
    Crop a region from the image.

    Args:
        region: (x_start_pct, y_start_pct, width_pct, height_pct) as fractions 0-1
    """
    w, h = img.size
    x_start = int(region[0] * w)
    y_start = int(region[1] * h)
    x_end = int((region[0] + region[2]) * w)
    y_end = int((region[1] + region[3]) * h)
    return img.crop((x_start, y_start, x_end, y_end))


# ---------------------------------------------------------------------------
# OCR Extraction
# ---------------------------------------------------------------------------

def _run_ocr(img: Image.Image) -> list[dict]:
    """
    Run Tesseract OCR on an image and return text with confidence scores.

    Returns list of dicts with: text, confidence, left, top, width, height
    """
    if not HAS_TESSERACT:
        return []

    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception as e:
        print(f"  [OCR] Tesseract error: {e}")
        return []

    results = []
    n_boxes = len(data["text"])
    for i in range(n_boxes):
        text = data["text"][i].strip()
        conf = int(data["conf"][i])
        if text and conf > 0:
            results.append({
                "text": text,
                "confidence": conf,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
            })

    return results


def _reconstruct_lines(ocr_results: list[dict]) -> list[dict]:
    """
    Group OCR word-level results into lines based on vertical position.
    Returns list of {"text": "full line text", "confidence": avg_confidence}
    """
    if not ocr_results:
        return []

    # Sort by top position, then left
    sorted_results = sorted(ocr_results, key=lambda r: (r["top"], r["left"]))

    lines = []
    current_line = []
    current_top = sorted_results[0]["top"]
    line_threshold = sorted_results[0]["height"] * 0.5 if sorted_results[0]["height"] > 0 else 10

    for result in sorted_results:
        if abs(result["top"] - current_top) > line_threshold:
            # New line
            if current_line:
                line_text = " ".join(r["text"] for r in current_line)
                avg_conf = sum(r["confidence"] for r in current_line) / len(current_line)
                lines.append({"text": line_text, "confidence": avg_conf})
            current_line = [result]
            current_top = result["top"]
        else:
            current_line.append(result)

    # Don't forget the last line
    if current_line:
        line_text = " ".join(r["text"] for r in current_line)
        avg_conf = sum(r["confidence"] for r in current_line) / len(current_line)
        lines.append({"text": line_text, "confidence": avg_conf})

    return lines


def _parse_measurements_from_text(lines: list[dict]) -> list[dict]:
    """
    Parse structured measurements from OCR text lines.

    Returns list of:
        {"measurement_name": str, "value": float, "unit": str, "context": "OCR", "confidence": float}
    """
    measurements = []

    for line_info in lines:
        text = line_info["text"]
        confidence = line_info["confidence"]

        # Skip low-confidence lines
        if confidence < config.OCR_CONFIDENCE_THRESHOLD:
            continue

        # Try each pattern
        for pattern in COMPILED_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group("name").strip()
                try:
                    value = float(match.group("value"))
                except (ValueError, IndexError):
                    continue

                try:
                    unit = match.group("unit") or ""
                except IndexError:
                    unit = ""

                # Validate: is this a plausible measurement?
                name_lower = name.lower().strip(" :-=")
                is_known = any(
                    known in name_lower or name_lower in known
                    for known in KNOWN_LABELS
                )

                # Accept if it matches a known label OR has high confidence
                if is_known or confidence >= 80:
                    measurements.append({
                        "measurement_name": _clean_label(name),
                        "value": value,
                        "unit": unit.strip(),
                        "context": "OCR",
                        "confidence": round(confidence, 1),
                    })

    return measurements


def _clean_label(label: str) -> str:
    """Normalize a measurement label from OCR."""
    label = label.strip(" :-=.")
    # Title case
    label = label.title()
    # Fix common OCR mistakes in ultrasound labels
    replacements = {
        "Rt ": "Right ", "Lt ": "Left ",
        "Rt.": "Right", "Lt.": "Left",
        "Cbd": "CBD", "Pv": "PV", "Ivc": "IVC",
        "Bpd": "BPD", "Hc": "HC", "Ac": "AC", "Fl": "FL",
        "Ef": "EF", "Fs": "FS",
        "Psv": "PSV", "Edv": "EDV", "Ri": "RI", "Pi": "PI",
    }
    for old, new in replacements.items():
        if old in label:
            label = label.replace(old, new)
    return label


# ---------------------------------------------------------------------------
# The scanner's measurement box (Philips: bottom-left, white on black)
# ---------------------------------------------------------------------------
# "+ Dist 9.70 cm", "x Dist 4.34 cm", "Dist1 8.41 cm", "Volume 418 ml". The
# box grows upward with more lines, and its small font loses decimal points
# unless enlarged, so it gets its own reading: a tall crop, enlarged 3x, at
# several contrast thresholds, keeping the reading with the most valid values.
MEASUREMENT_BOX = (0.0, 0.55, 0.32, 0.45)   # x, y, width, height as fractions
_BOX_LINE = re.compile(
    r"\b(?P<name>Dist|Volume|Vol|Area|Circ|Angle)\s*(?P<index>\d)?\s+"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm2|cm|mm|ml|cc)\b",
    re.IGNORECASE,
)


def _read_box(img: Image.Image, threshold: int) -> list[dict]:
    box = _crop_region(img.convert("L"), MEASUREMENT_BOX)
    box = box.resize((box.width * 3, box.height * 3), Image.LANCZOS)
    box = ImageOps.invert(box).point(lambda x: 255 if x > threshold else 0)
    try:
        text = pytesseract.image_to_string(box, config="--psm 6")
    except Exception as e:
        print(f"  [OCR] Tesseract error: {e}")
        return []
    found = []
    for m in _BOX_LINE.finditer(text):
        unit = m.group("unit").lower()
        value = m.group("value")
        # The scanner always prints lengths with a decimal ("9.70", "11.9");
        # a length without one is a misread ("894" for 8.94) - never guess
        if unit in ("cm", "mm") and "." not in value:
            continue
        found.append({
            "measurement_name": m.group("name").title() + (m.group("index") or ""),
            "value": float(value),
            "text": value,  # as printed on the image, e.g. "9.70"
            "unit": unit,
            "context": "OCR",
            "confidence": 90.0,
        })
    return found


def read_measurement_box(ds_or_img) -> list[dict]:
    """Every value in the scanner's on-image measurement box, in order."""
    if not HAS_PIL or not HAS_TESSERACT:
        return []
    img = ds_or_img if isinstance(ds_or_img, Image.Image) else _pixel_array_to_image(ds_or_img)
    if img is None:
        return []
    passes = [_read_box(img, t) for t in (140, 110, 90)]
    best = max(passes, key=len)
    # Each threshold can miss a different line: add uniquely named values
    # ("Dist1", "Volume") found only by another pass. Repeated plain "Dist"
    # lines can't be matched up between passes, so those come from `best` only.
    names = {m["measurement_name"] for m in best}
    for other in passes:
        for m in other:
            if m["measurement_name"] not in names and m["measurement_name"] != "Dist":
                best.append(m)
                names.add(m["measurement_name"])
    return best


# ---------------------------------------------------------------------------
# The scanner's Doppler box (Philips: right side, beside the colour bar)
# ---------------------------------------------------------------------------
# "PSV 39.2 cm/s", "EDV 14.5 cm/s", "RI 0.63", "PI 1.00", "S/D 2.7",
# "TAPV 24.7 cm/s". The colour bar next to it confuses a whole-image read.
# The values are tied by the scanner's own formulas, which are used to check
# every reading:  RI = (PSV - EDV) / PSV,  PI = (PSV - EDV) / TAPV,
# S/D = PSV / EDV.
DOPPLER_BOX = (0.72, 0.12, 0.235, 0.33)
_DOPPLER_LINE = re.compile(r"\b(PSV|EDV|MDV|RI|PI|S/D|TAPV|TAMV)\s*[:=]?\s*(\d+\.\d+)", re.IGNORECASE)
_VELOCITIES = ("PSV", "EDV", "MDV", "TAPV")


def _read_doppler(img: Image.Image, threshold: int) -> dict:
    box = _crop_region(img.convert("L"), DOPPLER_BOX)
    box = box.resize((box.width * 3, box.height * 3), Image.LANCZOS)
    box = ImageOps.invert(box).point(lambda x: 255 if x > threshold else 0)
    try:
        text = pytesseract.image_to_string(box, config="--psm 6")
    except Exception as e:
        print(f"  [OCR] Tesseract error: {e}")
        return {}
    found = {}
    for m in _DOPPLER_LINE.finditer(text):
        key = m.group(1).upper().replace("TAMV", "TAPV")
        found.setdefault(key, m.group(2))  # every value is printed with a decimal
    return found


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * max(abs(b), 0.01)


def read_doppler_box(ds_or_img) -> list[dict]:
    """
    PSV / EDV / RI / PI / S/D / TAPV from the Doppler box, checked against
    each other. A value that disagrees with the others is recalculated when
    its inputs agree, otherwise dropped - never printed unchecked.
    """
    if not HAS_PIL or not HAS_TESSERACT:
        return []
    img = ds_or_img if isinstance(ds_or_img, Image.Image) else _pixel_array_to_image(ds_or_img)
    if img is None:
        return []
    texts: dict[str, str] = {}
    for threshold in (140, 110, 90):
        for key, value in _read_doppler(img, threshold).items():
            texts.setdefault(key, value)
    if not texts:
        return []
    v = {k: float(t) for k, t in texts.items()}
    psv, edv, tapv = v.get("PSV"), v.get("EDV"), v.get("TAPV")

    # PSV and EDV are trusted when the scanner's RI agrees with them
    velocities_ok = psv and edv is not None and psv > edv and "RI" in v and _close((psv - edv) / psv, v["RI"], 0.04)
    if not velocities_ok:
        for k in ("PSV", "EDV", "MDV", "S/D"):
            v.pop(k, None)
    else:
        sd = psv / edv if edv else None
        if sd and ("S/D" not in v or not _close(sd, v["S/D"], 0.05)):
            v["S/D"] = round(sd, 1)
            texts["S/D"] = f"{v['S/D']:.1f}"
        if tapv and tapv > 0:
            pi = (psv - edv) / tapv
            if "PI" not in v or not _close(pi, v["PI"], 0.05):
                v["PI"] = round(pi, 2)
                texts["PI"] = f"{v['PI']:.2f}"
    order = ["PI", "RI", "S/D", "PSV", "EDV", "TAPV"]
    return [
        {"measurement_name": k, "value": v[k], "text": texts[k],
         "unit": "cm/s" if k in _VELOCITIES else "", "context": "OCR", "confidence": 90.0}
        for k in order if k in v
    ]


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_measurements_ocr(ds: Dataset) -> list[dict]:
    """
    Extract measurements from burned-in annotations in an ultrasound DICOM image.

    Args:
        ds: pydicom Dataset (must have pixel data)

    Returns:
        List of measurement dicts:
            measurement_name, value, unit, context ("OCR"), confidence
    """
    if not HAS_PIL or not HAS_TESSERACT:
        missing = []
        if not HAS_PIL:
            missing.append("Pillow")
        if not HAS_TESSERACT:
            missing.append("pytesseract")
        print(f"  [OCR] Skipping — missing dependencies: {', '.join(missing)}")
        return []

    img = _pixel_array_to_image(ds)
    if img is None:
        return []

    # The measurement box first: it reads the bottom-left area properly, so
    # the generic bottom-left region below (which cut its top lines off and
    # lost decimals) is skipped when the box has values
    all_measurements = read_measurement_box(img)
    # The Doppler box likewise has its own, checked reading; the generic
    # right-hand regions it overlaps are then skipped
    doppler = read_doppler_box(img)
    all_measurements += doppler

    # Strategy 1: OCR specific annotation regions
    for region_name, region_coords in config.OCR_REGIONS.items():
        if region_name == "bottom_left" and all_measurements:
            continue
        if region_name in ("top_right", "right_panel") and doppler:
            continue
        try:
            cropped = _crop_region(img, region_coords)
            processed = _preprocess_for_ocr(cropped)
            ocr_results = _run_ocr(processed)
            lines = _reconstruct_lines(ocr_results)
            measurements = _parse_measurements_from_text(lines)
            all_measurements.extend(measurements)
        except Exception as e:
            print(f"  [OCR] Error in region {region_name}: {e}")

    # Strategy 2: If nothing found in regions, try full image
    if not all_measurements:
        try:
            processed = _preprocess_for_ocr(img)
            ocr_results = _run_ocr(processed)
            lines = _reconstruct_lines(ocr_results)
            all_measurements = _parse_measurements_from_text(lines)
        except Exception as e:
            print(f"  [OCR] Error in full image OCR: {e}")

    # Deduplicate (same measurement might appear in overlapping regions)
    seen = set()
    unique = []
    for m in all_measurements:
        key = (m["measurement_name"].lower(), m["value"], m["unit"])
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return unique


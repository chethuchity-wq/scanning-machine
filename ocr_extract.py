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

    all_measurements = []

    # Strategy 1: OCR specific annotation regions
    for region_name, region_coords in config.OCR_REGIONS.items():
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


def extract_all_text_ocr(ds: Dataset) -> str:
    """
    Extract ALL text from the ultrasound image (for debugging/inspection).
    Returns the raw concatenated OCR text.
    """
    if not HAS_PIL or not HAS_TESSERACT:
        return ""

    img = _pixel_array_to_image(ds)
    if img is None:
        return ""

    processed = _preprocess_for_ocr(img)
    try:
        text = pytesseract.image_to_string(processed)
        return text
    except Exception as e:
        return f"OCR error: {e}"

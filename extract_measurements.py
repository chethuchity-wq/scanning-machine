"""
DICOM Structured Report (SR) measurement extractor.
Parses .dcm SR files and returns all numeric measurements
(e.g. liver size, kidney dimension, etc.) made by the radiologist.
"""

import pydicom
from pydicom.dataset import Dataset
from typing import Optional


def _get_code_meaning(sequence) -> str:
    """Return the CodeMeaning text from a code sequence item."""
    if sequence and len(sequence) > 0:
        return str(sequence[0].get("CodeMeaning", "Unknown"))
    return "Unknown"


def _walk_content_sequence(sequence, measurements: list, parent_label: str = "") -> None:
    """
    Recursively walk the SR ContentSequence tree.
    Every node with ValueType = 'NUM' is a numeric measurement.
    """
    for item in sequence:
        value_type = str(item.get("ValueType", "")).strip()

        # Get the concept (label) for this node
        concept_seq = item.get("ConceptNameCodeSequence", None)
        label = _get_code_meaning(concept_seq) if concept_seq else parent_label

        if value_type == "NUM":
            # Extract the numeric value and units
            measured_seq = item.get("MeasuredValueSequence", None)
            if measured_seq and len(measured_seq) > 0:
                mv = measured_seq[0]
                numeric_value = mv.get("NumericValue", None)
                units_seq = mv.get("MeasurementUnitsCodeSequence", None)
                units = _get_code_meaning(units_seq) if units_seq else ""

                if numeric_value is not None:
                    measurements.append({
                        "measurement_name": label,
                        "value": float(str(numeric_value)),
                        "unit": units,
                        "context": parent_label if parent_label != label else "",
                    })

        elif value_type == "CONTAINER":
            # Container groups related measurements (e.g. "Liver measurements")
            child_seq = item.get("ContentSequence", None)
            if child_seq:
                _walk_content_sequence(child_seq, measurements, parent_label=label)

        elif value_type == "TEXT":
            # Some systems store findings as free text — capture them too
            text_value = item.get("TextValue", "")
            if text_value:
                measurements.append({
                    "measurement_name": label,
                    "value": str(text_value),
                    "unit": "text",
                    "context": parent_label,
                })

        # Recurse into any nested ContentSequence regardless of type
        child_seq = item.get("ContentSequence", None)
        if child_seq and value_type not in ("CONTAINER",):
            _walk_content_sequence(child_seq, measurements, parent_label=label)


def extract_from_sr(ds: Dataset) -> list[dict]:
    """
    Extract all measurements from a DICOM Structured Report dataset.
    Returns a list of dicts: measurement_name, value, unit, context.
    """
    measurements = []
    content_seq = ds.get("ContentSequence", None)
    if content_seq:
        _walk_content_sequence(content_seq, measurements)
    return measurements


def extract_from_image(ds: Dataset) -> list[dict]:
    """
    Some Philips ultrasound images embed measurements directly in
    private tags or in the PixelDataInfo sequences rather than a
    separate SR file.  We surface what we can find.
    """
    measurements = []

    # Philips private group (2005,xxxx) — probe for known measurement tags
    philips_private_tags = [
        (0x2005, 0x1409),  # often contains annotation strings
        (0x200D, 0x0000),  # ultrasound region sequences
    ]
    for tag in philips_private_tags:
        elem = ds.get(tag, None)
        if elem is not None:
            try:
                measurements.append({
                    "measurement_name": f"Philips private {tag}",
                    "value": str(elem.value)[:200],
                    "unit": "private",
                    "context": "Philips private tag",
                })
            except Exception:
                pass

    # DICOM Ultrasound Region Sequence — contains physical delta / pixel spacing
    region_seq = ds.get((0x0018, 0x6011), None)  # SequenceOfUltrasoundRegions
    if region_seq:
        for i, region in enumerate(region_seq):
            px_x = region.get((0x0018, 0x602C), None)  # PhysicalDeltaX
            px_y = region.get((0x0018, 0x602E), None)  # PhysicalDeltaY
            unit_tag = region.get((0x0018, 0x6024), None)  # PhysicalUnitsXDirection
            if px_x is not None:
                measurements.append({
                    "measurement_name": f"Region {i+1} pixel spacing X",
                    "value": float(str(px_x.value)),
                    "unit": str(unit_tag.value) if unit_tag else "cm/pixel",
                    "context": "UltrasoundRegion",
                })
            if px_y is not None:
                measurements.append({
                    "measurement_name": f"Region {i+1} pixel spacing Y",
                    "value": float(str(px_y.value)),
                    "unit": str(unit_tag.value) if unit_tag else "cm/pixel",
                    "context": "UltrasoundRegion",
                })

    return measurements

"""
Normal Reference Ranges for Ultrasound Measurements
=====================================================
Contains normal adult reference values for common ultrasound measurements.
Used by the report generator to flag abnormal findings.

Sources:
- Rumack CM, et al. Diagnostic Ultrasound (5th ed.)
- ACR Appropriateness Criteria
- Standard radiology textbook references

NOTE: These are ADULT reference ranges. Pediatric/obstetric values differ.
Adjust for your clinical context.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class NormalRange:
    """Defines a normal reference range for a measurement."""
    organ: str
    measurement: str
    min_value: Optional[float]
    max_value: Optional[float]
    unit: str
    notes: str = ""
    gender_specific: str = "both"  # "male", "female", or "both"


# ---------------------------------------------------------------------------
# Reference Ranges Database
# ---------------------------------------------------------------------------

NORMAL_RANGES: list[NormalRange] = [
    # =========================================================================
    # LIVER
    # =========================================================================
    NormalRange(
        organ="Liver",
        measurement="Liver Span",
        min_value=None,
        max_value=15.5,
        unit="cm",
        notes="Mid-clavicular line, craniocaudal. >15.5 cm = hepatomegaly",
    ),
    NormalRange(
        organ="Liver",
        measurement="Liver Length",
        min_value=None,
        max_value=15.5,
        unit="cm",
        notes="Craniocaudal length. >15.5 cm suggests hepatomegaly",
    ),
    NormalRange(
        organ="Liver",
        measurement="Right Lobe",
        min_value=None,
        max_value=15.5,
        unit="cm",
        notes="Right lobe craniocaudal",
    ),
    NormalRange(
        organ="Liver",
        measurement="Left Lobe",
        min_value=None,
        max_value=10.0,
        unit="cm",
        notes="Left lobe AP dimension",
    ),
    NormalRange(
        organ="Liver",
        measurement="Caudate Lobe",
        min_value=None,
        max_value=3.5,
        unit="cm",
        notes="AP dimension of caudate",
    ),

    # =========================================================================
    # GALLBLADDER & BILIARY
    # =========================================================================
    NormalRange(
        organ="Gallbladder",
        measurement="GB Wall",
        min_value=None,
        max_value=3.0,
        unit="mm",
        notes="Wall thickness. >3mm = thickened (cholecystitis, etc.)",
    ),
    NormalRange(
        organ="Gallbladder",
        measurement="GB Length",
        min_value=None,
        max_value=10.0,
        unit="cm",
        notes="Normal length up to 10 cm",
    ),
    NormalRange(
        organ="Biliary",
        measurement="CBD",
        min_value=None,
        max_value=6.0,
        unit="mm",
        notes="Common bile duct. Normal <6mm (<8mm post-cholecystectomy, +1mm/decade after 60)",
    ),
    NormalRange(
        organ="Biliary",
        measurement="Common Bile Duct",
        min_value=None,
        max_value=6.0,
        unit="mm",
        notes="Same as CBD",
    ),
    NormalRange(
        organ="Biliary",
        measurement="CHD",
        min_value=None,
        max_value=4.0,
        unit="mm",
        notes="Common hepatic duct",
    ),
    NormalRange(
        organ="Biliary",
        measurement="IHBD",
        min_value=None,
        max_value=2.0,
        unit="mm",
        notes="Intrahepatic bile ducts. >2mm = dilated",
    ),

    # =========================================================================
    # PORTAL VEIN & HEPATIC VESSELS
    # =========================================================================
    NormalRange(
        organ="Liver",
        measurement="Portal Vein",
        min_value=None,
        max_value=13.0,
        unit="mm",
        notes="Main portal vein diameter. >13mm may suggest portal hypertension",
    ),
    NormalRange(
        organ="Liver",
        measurement="PV",
        min_value=None,
        max_value=13.0,
        unit="mm",
        notes="Portal vein. Same as above",
    ),
    NormalRange(
        organ="Liver",
        measurement="Portal Vein Velocity",
        min_value=16.0,
        max_value=40.0,
        unit="cm/s",
        notes="Normal hepatopetal flow 16-40 cm/s",
    ),
    NormalRange(
        organ="Liver",
        measurement="Hepatic Artery RI",
        min_value=0.55,
        max_value=0.7,
        unit="",
        notes="Hepatic artery resistive index",
    ),

    # =========================================================================
    # SPLEEN
    # =========================================================================
    NormalRange(
        organ="Spleen",
        measurement="Spleen",
        min_value=None,
        max_value=12.0,
        unit="cm",
        notes="Spleen length. >12 cm = splenomegaly",
    ),
    NormalRange(
        organ="Spleen",
        measurement="Spleen Length",
        min_value=None,
        max_value=12.0,
        unit="cm",
        notes=">13 cm = moderate, >17 cm = massive splenomegaly",
    ),
    NormalRange(
        organ="Spleen",
        measurement="Splenic Length",
        min_value=None,
        max_value=12.0,
        unit="cm",
        notes="Same as Spleen Length",
    ),

    # =========================================================================
    # KIDNEYS
    # =========================================================================
    NormalRange(
        organ="Kidney",
        measurement="Right Kidney",
        min_value=9.0,
        max_value=12.0,
        unit="cm",
        notes="Right kidney length. Normal 9-12 cm in adults",
    ),
    NormalRange(
        organ="Kidney",
        measurement="Left Kidney",
        min_value=9.0,
        max_value=12.0,
        unit="cm",
        notes="Left kidney length. Normal 9-12 cm (left slightly larger)",
    ),
    NormalRange(
        organ="Kidney",
        measurement="Rt Kidney",
        min_value=9.0,
        max_value=12.0,
        unit="cm",
        notes="Right kidney length",
    ),
    NormalRange(
        organ="Kidney",
        measurement="Lt Kidney",
        min_value=9.0,
        max_value=12.0,
        unit="cm",
        notes="Left kidney length",
    ),
    NormalRange(
        organ="Kidney",
        measurement="Kidney Length",
        min_value=9.0,
        max_value=12.0,
        unit="cm",
        notes="Either kidney",
    ),
    NormalRange(
        organ="Kidney",
        measurement="Renal Length",
        min_value=9.0,
        max_value=12.0,
        unit="cm",
        notes="Either kidney",
    ),
    NormalRange(
        organ="Kidney",
        measurement="Cortex",
        min_value=1.0,
        max_value=1.5,
        unit="cm",
        notes="Renal cortical thickness. <1cm = thinned (CKD)",
    ),
    NormalRange(
        organ="Kidney",
        measurement="Renal RI",
        min_value=0.5,
        max_value=0.7,
        unit="",
        notes="Renal resistive index. >0.7 = abnormal",
    ),
    NormalRange(
        organ="Kidney",
        measurement="RI",
        min_value=0.5,
        max_value=0.7,
        unit="",
        notes="Resistive index (renal context)",
    ),

    # =========================================================================
    # PANCREAS
    # =========================================================================
    NormalRange(
        organ="Pancreas",
        measurement="Pancreas Head",
        min_value=None,
        max_value=3.0,
        unit="cm",
        notes="Head AP dimension. Normal up to 3.0 cm",
    ),
    NormalRange(
        organ="Pancreas",
        measurement="Pancreas Body",
        min_value=None,
        max_value=2.5,
        unit="cm",
        notes="Body AP dimension. Normal up to 2.5 cm",
    ),
    NormalRange(
        organ="Pancreas",
        measurement="Pancreas Tail",
        min_value=None,
        max_value=2.0,
        unit="cm",
        notes="Tail AP dimension. Normal up to 2.0 cm",
    ),
    NormalRange(
        organ="Pancreas",
        measurement="PD",
        min_value=None,
        max_value=3.0,
        unit="mm",
        notes="Pancreatic duct. Normal <3mm",
    ),
    NormalRange(
        organ="Pancreas",
        measurement="Pancreatic Duct",
        min_value=None,
        max_value=3.0,
        unit="mm",
        notes="Main pancreatic duct. >3mm in body = dilated",
    ),

    # =========================================================================
    # AORTA & IVC
    # =========================================================================
    NormalRange(
        organ="Aorta",
        measurement="Aorta",
        min_value=None,
        max_value=3.0,
        unit="cm",
        notes="Abdominal aorta diameter. >3cm = aneurysm",
    ),
    NormalRange(
        organ="Aorta",
        measurement="Aorta Diameter",
        min_value=None,
        max_value=3.0,
        unit="cm",
        notes=">3 cm = AAA",
    ),
    NormalRange(
        organ="IVC",
        measurement="IVC",
        min_value=None,
        max_value=2.1,
        unit="cm",
        notes="Inferior vena cava. >2.1 cm with <50% collapse suggests elevated RA pressure",
    ),

    # =========================================================================
    # THYROID
    # =========================================================================
    NormalRange(
        organ="Thyroid",
        measurement="Rt Thyroid",
        min_value=None,
        max_value=2.0,
        unit="cm",
        notes="Right lobe AP dimension. Normal each lobe <2cm AP x <2cm transverse x <5cm length",
    ),
    NormalRange(
        organ="Thyroid",
        measurement="Lt Thyroid",
        min_value=None,
        max_value=2.0,
        unit="cm",
        notes="Left lobe AP dimension",
    ),
    NormalRange(
        organ="Thyroid",
        measurement="Right Thyroid",
        min_value=None,
        max_value=2.0,
        unit="cm",
        notes="Right lobe",
    ),
    NormalRange(
        organ="Thyroid",
        measurement="Left Thyroid",
        min_value=None,
        max_value=2.0,
        unit="cm",
        notes="Left lobe",
    ),
    NormalRange(
        organ="Thyroid",
        measurement="Isthmus",
        min_value=None,
        max_value=0.5,
        unit="cm",
        notes="Isthmus AP thickness. Normal <5mm",
    ),

    # =========================================================================
    # PROSTATE
    # =========================================================================
    NormalRange(
        organ="Prostate",
        measurement="Prostate Volume",
        min_value=None,
        max_value=30.0,
        unit="ml",
        notes="Normal <30 ml. 30-80 = BPH",
        gender_specific="male",
    ),
    NormalRange(
        organ="Prostate",
        measurement="Prostate",
        min_value=None,
        max_value=4.0,
        unit="cm",
        notes="AP dimension",
        gender_specific="male",
    ),

    # =========================================================================
    # UTERUS (basic)
    # =========================================================================
    NormalRange(
        organ="Uterus",
        measurement="Uterus Length",
        min_value=6.0,
        max_value=9.0,
        unit="cm",
        notes="Uterine length (nulliparous 6-8, multiparous up to 9)",
        gender_specific="female",
    ),
    NormalRange(
        organ="Uterus",
        measurement="Endometrium",
        min_value=None,
        max_value=14.0,
        unit="mm",
        notes="Endometrial thickness. Premenopausal varies with cycle; postmenopausal >5mm = abnormal",
        gender_specific="female",
    ),

    # =========================================================================
    # CARDIAC (basic echo measurements)
    # =========================================================================
    NormalRange(
        organ="Heart",
        measurement="EF",
        min_value=55.0,
        max_value=70.0,
        unit="%",
        notes="Ejection fraction. <55% = reduced, <40% = severely reduced",
    ),
    NormalRange(
        organ="Heart",
        measurement="FS",
        min_value=25.0,
        max_value=45.0,
        unit="%",
        notes="Fractional shortening",
    ),
    NormalRange(
        organ="Heart",
        measurement="IVS",
        min_value=0.6,
        max_value=1.1,
        unit="cm",
        notes="Interventricular septum thickness",
    ),
    NormalRange(
        organ="Heart",
        measurement="LVPW",
        min_value=0.6,
        max_value=1.1,
        unit="cm",
        notes="LV posterior wall thickness",
    ),
    NormalRange(
        organ="Heart",
        measurement="LA",
        min_value=1.9,
        max_value=4.0,
        unit="cm",
        notes="Left atrium AP dimension",
    ),
]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normalize measurement name for matching."""
    return text.lower().strip().replace(".", "").replace("-", " ")


def find_normal_range(measurement_name: str, unit: str = "") -> Optional[NormalRange]:
    """
    Find the matching normal range for a given measurement name.

    Args:
        measurement_name: The label from the DICOM/OCR extraction
        unit: The unit of the measurement (helps disambiguate)

    Returns:
        NormalRange object if found, None otherwise
    """
    name_norm = _normalize(measurement_name)

    # Try exact match first
    for nr in NORMAL_RANGES:
        if _normalize(nr.measurement) == name_norm:
            # If unit provided, check it matches
            if unit and nr.unit and unit.lower() != nr.unit.lower():
                continue
            return nr

    # Try partial match (measurement name contains the range label or vice versa)
    for nr in NORMAL_RANGES:
        nr_norm = _normalize(nr.measurement)
        if nr_norm in name_norm or name_norm in nr_norm:
            if unit and nr.unit and unit.lower() != nr.unit.lower():
                continue
            return nr

    return None


def evaluate_measurement(measurement_name: str, value: float, unit: str = "") -> dict:
    """
    Evaluate a measurement against normal ranges.

    Returns:
        {
            "status": "normal" | "high" | "low" | "unknown",
            "normal_range": NormalRange or None,
            "message": str  (human-readable assessment)
        }
    """
    nr = find_normal_range(measurement_name, unit)

    if nr is None:
        return {
            "status": "unknown",
            "normal_range": None,
            "message": f"No reference range available for '{measurement_name}'",
        }

    status = "normal"
    messages = []

    if nr.max_value is not None and value > nr.max_value:
        status = "high"
        messages.append(f"ABOVE normal (max {nr.max_value} {nr.unit})")
    elif nr.min_value is not None and value < nr.min_value:
        status = "low"
        messages.append(f"BELOW normal (min {nr.min_value} {nr.unit})")
    else:
        range_str = ""
        if nr.min_value is not None and nr.max_value is not None:
            range_str = f" (normal: {nr.min_value}-{nr.max_value} {nr.unit})"
        elif nr.max_value is not None:
            range_str = f" (normal: <{nr.max_value} {nr.unit})"
        elif nr.min_value is not None:
            range_str = f" (normal: >{nr.min_value} {nr.unit})"
        messages.append(f"Within normal limits{range_str}")

    return {
        "status": status,
        "normal_range": nr,
        "message": messages[0] if messages else "",
    }


def get_organ_ranges(organ: str) -> list[NormalRange]:
    """Get all normal ranges for a specific organ."""
    organ_lower = organ.lower()
    return [nr for nr in NORMAL_RANGES if nr.organ.lower() == organ_lower]

"""
Ultrasound Report PDF Generator
=================================
Generates a clinical PDF report from extracted ultrasound measurements.
Includes patient info, measurements table with normal range comparison,
and flagged abnormal findings.

Usage:
    from report_generator import generate_report

    measurements = [
        {"measurement_name": "Liver Span", "value": 14.2, "unit": "cm", "context": "SR"},
        {"measurement_name": "Right Kidney", "value": 10.5, "unit": "cm", "context": "SR"},
    ]
    patient_info = {
        "patient_name": "John Doe",
        "patient_id": "P001",
        "dob": "1980-05-15",
        "study_date": "2026-06-30",
        "referring_physician": "Dr. Smith",
    }
    generate_report(patient_info, measurements, output_path="report.pdf")
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from fpdf import FPDF

import config
from normal_ranges import evaluate_measurement, find_normal_range


# ---------------------------------------------------------------------------
# Custom PDF class
# ---------------------------------------------------------------------------

class UltrasoundReportPDF(FPDF):
    """Custom PDF with header/footer for ultrasound reports."""

    def __init__(self, patient_info: dict):
        super().__init__()
        self.patient_info = patient_info
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        # Clinic logo (if configured)
        if config.CLINIC_LOGO and Path(config.CLINIC_LOGO).exists():
            self.image(config.CLINIC_LOGO, 10, 8, 20)
            self.set_x(35)
        else:
            self.set_x(10)

        # Clinic name
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 7, config.CLINIC_NAME, new_x="LMARGIN", new_y="NEXT")

        # Clinic address & phone
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100, 100, 100)
        if config.CLINIC_ADDRESS:
            self.cell(0, 4, config.CLINIC_ADDRESS, new_x="LMARGIN", new_y="NEXT")
        if config.CLINIC_PHONE:
            self.cell(0, 4, f"Phone: {config.CLINIC_PHONE}", new_x="LMARGIN", new_y="NEXT")

        self.set_text_color(0, 0, 0)

        # Divider line
        self.ln(3)
        self.set_draw_color(0, 102, 153)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(180, 180, 180)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 4, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
        self.cell(
            0, 4,
            f"Page {self.page_no()}/{{nb}} | This is a computer-generated report. Clinical correlation advised.",
            align="C",
        )
        self.set_text_color(0, 0, 0)


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _add_patient_section(pdf: UltrasoundReportPDF, patient_info: dict):
    """Add patient demographics section."""
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(240, 248, 255)
    pdf.cell(0, 8, "  ULTRASOUND REPORT", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Patient details in a 2-column layout
    pdf.set_font("Helvetica", "", 10)
    details = [
        ("Patient Name", patient_info.get("patient_name", "N/A")),
        ("Patient ID", patient_info.get("patient_id", "N/A")),
        ("Date of Birth", patient_info.get("dob", "N/A")),
        ("Study Date", patient_info.get("study_date", "N/A")),
        ("Accession No.", patient_info.get("accession_no", "N/A")),
        ("Referring Dr.", patient_info.get("referring_physician", "N/A")),
        ("Modality", patient_info.get("modality", "US")),
        ("Description", patient_info.get("description", "Ultrasound")),
    ]

    col_width = 95
    for i in range(0, len(details), 2):
        # Left column
        label, value = details[i]
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(25, 5, f"{label}:", new_x="END")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(col_width - 25, 5, f" {value}", new_x="END")

        # Right column (if exists)
        if i + 1 < len(details):
            label, value = details[i + 1]
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(25, 5, f"{label}:", new_x="END")
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(col_width - 25, 5, f" {value}", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.ln()

    pdf.ln(6)


def _add_measurements_table(pdf: UltrasoundReportPDF, measurements: list[dict]):
    """Add measurements table with normal range comparison."""
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(0, 102, 153)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 7, "  MEASUREMENTS", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    if not measurements:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "No measurements extracted.", new_x="LMARGIN", new_y="NEXT")
        return

    # Table header
    col_widths = [55, 25, 15, 45, 25, 25]  # name, value, unit, normal range, status, source
    headers = ["Measurement", "Value", "Unit", "Normal Range", "Status", "Source"]

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 240, 250)
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 6, header, border=1, fill=True, new_x="END")
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 9)
    row_alternate = False

    for m in measurements:
        name = m.get("measurement_name", "Unknown")
        value = m.get("value", "")
        unit = m.get("unit", "")
        source = m.get("context", "")

        # Evaluate against normal range
        if isinstance(value, (int, float)):
            evaluation = evaluate_measurement(name, value, unit)
            status = evaluation["status"]
            nr = evaluation.get("normal_range")
            if nr:
                range_str = ""
                if nr.min_value is not None and nr.max_value is not None:
                    range_str = f"{nr.min_value} - {nr.max_value} {nr.unit}"
                elif nr.max_value is not None:
                    range_str = f"< {nr.max_value} {nr.unit}"
                elif nr.min_value is not None:
                    range_str = f"> {nr.min_value} {nr.unit}"
            else:
                range_str = "-"
        else:
            status = "text"
            range_str = "-"

        # Row background color
        if row_alternate:
            pdf.set_fill_color(248, 248, 248)
        else:
            pdf.set_fill_color(255, 255, 255)

        # Status color
        if status == "high":
            pdf.set_text_color(200, 0, 0)
            status_text = "HIGH"
        elif status == "low":
            pdf.set_text_color(200, 100, 0)
            status_text = "LOW"
        elif status == "normal":
            pdf.set_text_color(0, 128, 0)
            status_text = "Normal"
        else:
            pdf.set_text_color(100, 100, 100)
            status_text = "-"

        # Draw row
        pdf.set_text_color(0, 0, 0)
        pdf.cell(col_widths[0], 5.5, str(name)[:30], border="LB", fill=True, new_x="END")

        value_str = f"{value:.1f}" if isinstance(value, float) else str(value)[:15]
        pdf.cell(col_widths[1], 5.5, value_str, border="B", fill=True, new_x="END")
        pdf.cell(col_widths[2], 5.5, str(unit)[:8], border="B", fill=True, new_x="END")
        pdf.cell(col_widths[3], 5.5, range_str[:25], border="B", fill=True, new_x="END")

        # Status with color
        if status == "high":
            pdf.set_text_color(200, 0, 0)
        elif status == "low":
            pdf.set_text_color(200, 100, 0)
        elif status == "normal":
            pdf.set_text_color(0, 128, 0)
        else:
            pdf.set_text_color(100, 100, 100)
        pdf.cell(col_widths[4], 5.5, status_text, border="B", fill=True, new_x="END")

        pdf.set_text_color(100, 100, 100)
        pdf.cell(col_widths[5], 5.5, source[:10], border="RB", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

        row_alternate = not row_alternate

    pdf.ln(6)


def _add_findings_section(pdf: UltrasoundReportPDF, measurements: list[dict]):
    """Add findings/impressions section highlighting abnormalities."""
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(0, 102, 153)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 7, "  FINDINGS & IMPRESSIONS", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    abnormals = []
    normals = []

    for m in measurements:
        name = m.get("measurement_name", "Unknown")
        value = m.get("value", "")
        unit = m.get("unit", "")

        if isinstance(value, (int, float)):
            evaluation = evaluate_measurement(name, value, unit)
            if evaluation["status"] in ("high", "low"):
                abnormals.append({
                    "name": name,
                    "value": value,
                    "unit": unit,
                    "status": evaluation["status"],
                    "message": evaluation["message"],
                    "organ": evaluation["normal_range"].organ if evaluation["normal_range"] else "",
                })
            elif evaluation["status"] == "normal":
                normals.append(name)

    # Abnormal findings
    if abnormals:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 6, "Abnormal Findings:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 9)

        for i, abn in enumerate(abnormals, 1):
            finding = (
                f"  {i}. {abn['name']}: {abn['value']} {abn['unit']} - "
                f"{abn['message']}"
            )
            pdf.set_text_color(180, 0, 0)
            pdf.cell(0, 5, finding, new_x="LMARGIN", new_y="NEXT")

        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)
    else:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 128, 0)
        pdf.cell(0, 6, "No abnormal findings detected.", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    # Normal findings summary
    if normals:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Within Normal Limits:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        normal_text = ", ".join(normals)
        pdf.multi_cell(0, 5, f"  {normal_text}")
        pdf.ln(3)

    # Disclaimer
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(128, 128, 128)
    pdf.multi_cell(
        0, 4,
        "Note: This report is auto-generated from DICOM measurements. "
        "Normal ranges are based on adult reference values. "
        "Clinical correlation and radiologist review are essential before diagnosis.",
    )
    pdf.set_text_color(0, 0, 0)


def _add_signature_section(pdf: UltrasoundReportPDF):
    """Add signature area at bottom."""
    pdf.ln(15)
    pdf.set_font("Helvetica", "", 10)

    # Two signature blocks
    y = pdf.get_y()
    pdf.set_x(15)
    pdf.cell(80, 5, "_" * 30, new_x="END")
    pdf.cell(20, 5, "", new_x="END")
    pdf.cell(80, 5, "_" * 30, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_x(15)
    pdf.cell(80, 5, "Sonographer", new_x="END")
    pdf.cell(20, 5, "", new_x="END")
    pdf.cell(80, 5, "Radiologist", new_x="LMARGIN", new_y="NEXT")


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

def generate_report(
    patient_info: dict,
    measurements: list[dict],
    output_path: str = None,
) -> Path:
    """
    Generate a PDF ultrasound report.

    Args:
        patient_info: Dict with patient_name, patient_id, dob, study_date, etc.
        measurements: List of measurement dicts from SR/OCR extraction.
            Each dict: measurement_name, value, unit, context
        output_path: Output PDF path (default: auto-generated in config.OUTPUT_DIR)

    Returns:
        Path to the generated PDF file
    """
    # Determine output path
    if output_path is None:
        output_dir = Path(config.OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        patient_name = patient_info.get("patient_name", "unknown").replace(" ", "_").replace("^", "_")
        study_date = patient_info.get("study_date", datetime.now().strftime("%Y-%m-%d"))
        filename = f"US_Report_{patient_name}_{study_date}.pdf"
        output_path = output_dir / filename
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # Sort measurements by organ grouping
    measurements_sorted = sorted(
        measurements,
        key=lambda m: (
            _get_organ_order(m.get("measurement_name", "")),
            m.get("measurement_name", ""),
        ),
    )

    # Build PDF
    pdf = UltrasoundReportPDF(patient_info)
    pdf.alias_nb_pages()
    pdf.add_page()

    _add_patient_section(pdf, patient_info)
    _add_measurements_table(pdf, measurements_sorted)
    _add_findings_section(pdf, measurements_sorted)
    _add_signature_section(pdf)

    # Save
    pdf.output(str(output_path))
    print(f"  [REPORT] Generated: {output_path}")

    return output_path


def _get_organ_order(measurement_name: str) -> int:
    """Return sort order by organ for grouped display."""
    name_lower = measurement_name.lower()
    organ_order = [
        ("liver", 1), ("hepat", 1),
        ("gb", 2), ("gallbladder", 2), ("bile", 2), ("cbd", 2), ("biliary", 2),
        ("portal", 3), ("pv", 3),
        ("spleen", 4), ("splenic", 4),
        ("kidney", 5), ("renal", 5),
        ("pancrea", 6),
        ("aorta", 7), ("ivc", 7),
        ("thyroid", 8), ("isthmus", 8),
        ("prostate", 9),
        ("uterus", 10), ("endo", 10),
        ("heart", 11), ("ef", 11), ("fs", 11), ("lv", 11),
    ]
    for keyword, order in organ_order:
        if keyword in name_lower:
            return order
    return 99  # Unknown organs at the end

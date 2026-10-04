"""
Ultrasound Report Generator (DOCX)
==================================
Fills the clinic's Word form for a scan type (templates/<scan_type>.docx)
with the patient's details and the scanner's measurements, adds the scan
images on their own page, and saves the report as an editable .docx.

    from fill_report import generate_report
    generate_report("growth_scan", {"patient_name": "...", "date": "2026-10-04", ...})

The forms are made by tools/build_templates.py and may be edited in Word.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The reporting doctor's name is printed in the PCPNDT declaration - a
# statutory statement - so it is never hardcoded here. The pipeline passes the
# clinic's values (dashboard Settings page) in the data dict as "_doctor_name"
# / "_doctor_qual"; these config values are only a fallback.
# When no name is set anywhere, the report prints a blank line for the doctor
# to fill in by hand rather than another doctor's name.
DOCTOR_NAME = getattr(config, "DOCTOR_NAME", "")
DOCTOR_QUAL = getattr(config, "DOCTOR_QUAL", "")
REFERRING_DEFAULT = getattr(config, "REFERRING_DEFAULT", "")
DOCTOR_BLANK = "____________________"
OUTPUT_DIR = Path("reports/filled")

# The clinic's own report formats, one per scan type (templates/<scan_type>.docx).
# Blanks are marked {{field}}; see _fill_template.
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_DATE_FIELDS = ("date", "lmp", "edd_scan", "edd_lmp")
# A value the scan didn't provide prints as a fill-in line ("Normal in size
# (____ cm)") so the doctor can't miss it - not as "( cm)". Patient-box fields
# stay empty: an empty box is already obvious.
MISSING_VALUE = "____"
_LEAVE_EMPTY = {"patient_name", "patient_id", "age", "date", "ref_by", "lmp",
                "clinical_details", "clinical_data", "doctor_qual"}

# Report types: one clinic form each in templates/
SCAN_TYPES = (
    "early_pregnancy", "nt_scan", "anomaly_scan", "growth_scan", "follicular_study",
    "abdomen_pelvis_female", "abdomen_pelvis_male", "breast_scan",
)


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

def _heading(doc: Document, text: str, size: int = 13, center: bool = True) -> None:
    p = doc.add_paragraph()
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(size)


IMAGES_HEADING = "ULTRASOUND IMAGES"


def _add_images_section(doc: Document, images: list | None, images_per_row: int = 2) -> None:
    """
    Append a grid of ultrasound scan images, if any were provided. Each item
    is the image bytes, or (scan image name, bytes): the name ("image_03.jpg",
    as in the dashboard's scan panel) is stored as the picture's description,
    so the dashboard knows which scan images are in the report.
    """
    if not images:
        return

    # Images on their own page, so they never split the report text
    doc.add_page_break()
    _heading(doc, IMAGES_HEADING, size=14)

    image_width = Inches(3.1)
    for row_start in range(0, len(images), images_per_row):
        row_images = images[row_start:row_start + images_per_row]
        table = doc.add_table(rows=1, cols=images_per_row)
        for col, item in enumerate(row_images):
            name, img_bytes = item if isinstance(item, tuple) else ("", item)
            paragraph = table.rows[0].cells[col].paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run()
            try:
                shape = run.add_picture(io.BytesIO(img_bytes), width=image_width)
            except Exception:
                continue
            if name:
                shape._inline.docPr.set("descr", name)


def _doctor(d: dict) -> tuple[str, str]:
    """(name, qualification) for this report: data dict first, then config."""
    name = (d.get("_doctor_name") or DOCTOR_NAME).strip()
    qual = (d.get("_doctor_qual") or DOCTOR_QUAL).strip()
    return name, qual


def _non_clobbering_path(path: Path) -> Path:
    """
    Return `path`, or the first free `name_2.docx`, `name_3.docx`, ... variant
    if it is already taken.

    Reports are NEVER overwritten. The doctor edits the generated .docx in
    place and saves over it, so an overwrite silently destroys a completed,
    signed report - and the pipeline can legitimately re-run on the same
    patient (a second scan the same day, or Orthanc re-firing StableStudy
    when late instances arrive for an already-processed study).
    """
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find a free filename for {path}")


def _save(doc: Document, patient_name: str, scan_type: str, date: str = "", folder: str = "") -> Path:
    """
    Save into `folder` (the report folder set in the dashboard's Settings), or
    reports/filled when none is set. If that folder can't be written (e.g. a
    network share that is down) the report is saved locally instead - the
    pipeline flags it - rather than being lost.
    """
    safe_name = "".join(c for c in patient_name if c.isalnum() or c in " ._-").strip()
    # Prefer the report's own date over today's - a study processed the day
    # after it was acquired should still be filed under the scan date.
    date_str = _date_for_filename(date)
    filename = f"{safe_name}_{scan_type}_{date_str}.docx"
    if folder:
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            path = _non_clobbering_path(Path(folder) / filename)
            doc.save(path)
            return path
        except OSError as e:
            print(f"  [DOCX] Cannot save in the report folder {folder}: {e} - saving locally")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _non_clobbering_path(OUTPUT_DIR / filename)
    doc.save(path)
    return path


def _date_for_filename(date: str) -> str:
    """Normalize a report date to YYYYMMDD, falling back to today."""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(date.strip(), fmt).strftime("%Y%m%d")
        except (ValueError, AttributeError):
            continue
    return datetime.today().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Filling the clinic's forms
# ---------------------------------------------------------------------------

def _replace_span(paragraph, start: int, end: int, new: str) -> None:
    """
    Replace characters [start, end) of a paragraph's text, even when they span
    several runs. Word splits text into runs unpredictably (spell-check, edit
    history), so a placeholder typed as "{{crl}}" may be stored as "{{", "crl",
    "}}". The replacement takes the formatting of the run where it starts.
    """
    pos = 0
    first = None
    for run in paragraph.runs:
        run_start, run_end = pos, pos + len(run.text)
        pos = run_end
        if run_end <= start or run_start >= end:
            continue
        text = run.text
        suffix = text[end - run_start:] if run_end > end else ""
        if first is None:
            first = run
            run.text = text[:start - run_start] + new + suffix
        else:
            run.text = suffix


def _iter_paragraphs(doc: Document):
    """Every paragraph in the body, tables (including nested) and headers/footers."""
    def walk(container):
        for paragraph in container.paragraphs:
            yield paragraph
        for table in container.tables:
            for row in table.rows:
                for cell in row.cells:
                    yield from walk(cell)

    yield from walk(doc)
    for section in doc.sections:
        for part in (section.header, section.footer):
            yield from walk(part)


def _display_date(value: str) -> str:
    """Dates print as DD/MM/YYYY, the clinic's format; anything unparseable as-is."""
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return str(value)


def _template_values(d: dict) -> dict:
    """Placeholder values for a template: the data dict plus derived fields."""
    values = {
        key: str(value) for key, value in d.items()
        if not key.startswith("_") and isinstance(value, (str, int, float))
    }
    for key in _DATE_FIELDS:
        if values.get(key):
            values[key] = _display_date(values[key])
    doctor_name, doctor_qual = _doctor(d)
    values["doctor_name"] = doctor_name or DOCTOR_BLANK
    values["doctor_qual"] = doctor_qual
    values["ref_by"] = d.get("ref_by") or REFERRING_DEFAULT
    return values


def _fill_template(template: Path, d: dict) -> Document:
    """
    Open a clinic template and fill every {{field}}. A field with no value is
    left blank for the doctor to write in, exactly as the nurse's blank form.
    """
    doc = Document(str(template))
    values = _template_values(d)
    for paragraph in _iter_paragraphs(doc):
        # Offsets must come from the same runs _replace_span edits
        # (paragraph.text also counts hyperlink text)
        text = "".join(run.text for run in paragraph.runs)
        if "{{" not in text:
            continue
        # Right to left, so earlier match offsets stay valid
        for match in reversed(list(_PLACEHOLDER_RE.finditer(text))):
            field = match.group(1)
            value = values.get(field, "")
            if not value.strip() and field not in _LEAVE_EMPTY:
                value = MISSING_VALUE
            _replace_span(paragraph, match.start(), match.end(), value)
    return doc


def generate_report(scan_type: str, data: dict) -> Path:
    """
    Fill the clinic's form for `scan_type` (templates/<scan_type>.docx) with
    `data` (patient details and measurements), add the scan images, save it
    and return the path of the .docx.
    """
    if scan_type not in SCAN_TYPES:
        raise ValueError(f"Unknown scan type '{scan_type}'. Valid types: {list(SCAN_TYPES)}")
    template = TEMPLATE_DIR / f"{scan_type}.docx"
    if not template.exists():
        raise FileNotFoundError(
            f"Missing {template} - run: python tools/build_templates.py {scan_type}")
    doc = _fill_template(template, data)
    _add_images_section(doc, data.get("_images"))
    return _save(doc, data.get("patient_name", "patient"), scan_type, data.get("date", ""),
                 data.get("_report_folder", ""))

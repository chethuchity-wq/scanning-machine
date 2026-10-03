"""
Build the clinic's report templates (templates/<scan_type>.docx).

Layout only: the wording is the clinic's own forms. Each template is printed on
the clinic's pre-printed letterhead, so there is no header and the top margin
leaves room for it; black and white only.

    python tools/build_templates.py

WARNING: overwrites templates/*.docx. If the clinic has since edited a
template in Word, make the same change here first or it will be lost.
Placeholders ({{field}}) are filled by fill_report._fill_template; their names
and units must match pipeline._FIELD_UNITS.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

# Page: A4, printed on the clinic's pre-printed letterhead, which needs 3.5 cm
# clear at the top (its header) and 2.5 cm at the bottom (its footer); 1.5 cm
# at the sides. The page-number line sits just above the footer band.
PAGE_W, PAGE_H = Cm(21.0), Cm(29.7)
MARGIN_TOP, MARGIN_BOTTOM = Cm(3.5), Cm(3.2)
FOOTER_DISTANCE = Cm(2.6)
MARGIN_SIDE = Cm(1.5)
CONTENT_W = (21.0 - 2 * 1.5) / 2.54  # inches

FONT = "Calibri"
BODY_PT, TABLE_PT, NOTE_PT = 11, 10.5, 9


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def new_doc() -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = PAGE_W, PAGE_H
    section.top_margin, section.bottom_margin = MARGIN_TOP, MARGIN_BOTTOM
    section.left_margin = section.right_margin = MARGIN_SIDE
    section.footer_distance = FOOTER_DISTANCE

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(BODY_PT)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.line_spacing = 1.0
    # Word re-renders page-number fields in the paragraph style's font, so
    # the footer's size is set on the style, not the runs
    doc.styles["Footer"].font.size = Pt(8)
    _footer(section)
    return doc


def _field(paragraph, instr: str) -> None:
    """Append a Word field (PAGE, NUMPAGES) to a paragraph."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "16")  # half-points: 8pt
    r_pr.append(size)
    run.append(r_pr)
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def _footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.style = "Footer"
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run("{{patient_name}}   |   Page ")
    _field(p, "PAGE")
    p.add_run(" of ")
    _field(p, "NUMPAGES")
    for run in p.runs:
        run.font.size = Pt(8)


def title(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run(text)
    run.bold = True
    run.underline = True
    run.font.size = Pt(14)


def heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(BODY_PT)


def _cell_text(cell, text: str, bold: bool = False, size: float = TABLE_PT,
               align=None) -> None:
    """Write text into a cell; a list writes one paragraph per item."""
    items = text if isinstance(text, list) else [text]
    for i, item in enumerate(items):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(1)
        if align is not None:
            p.alignment = align
        # (sub-label, text) pairs print the sub-label in bold
        label, body = item if isinstance(item, tuple) else ("", item)
        if label:
            r = p.add_run(label + " ")
            r.bold = True
            r.font.size = Pt(size)
        r = p.add_run(body)
        r.bold = bold
        r.font.size = Pt(size)


def _set_widths(table, widths: list[float]) -> None:
    """Word sizes columns from the table grid; cell widths alone are ignored."""
    for col, width in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        col.set(qn("w:w"), str(int(width * 1440)))  # twips
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Inches(width)


def _keep_rows_together(table) -> None:
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)


def keep_table_together(table) -> None:
    """
    Keep a short table on one page: every row but the last keeps with the
    next, so Word moves the whole table (and its heading, which keeps with
    the table) to the next page instead of splitting it.
    """
    for row in table.rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True


def grid_table(doc: Document, rows: list[list[str]], widths: list[float],
               header: bool = False, label_cols: tuple[int, ...] = (0,),
               center_cols: tuple[int, ...] = ()) -> None:
    """Bordered table. Header row and label columns are bold."""
    table = doc.add_table(rows=len(rows), cols=len(widths))
    table.style = "Table Grid"
    table.autofit = False
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            cell = table.rows[r].cells[c]
            cell.width = Inches(widths[c])
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            bold = (header and r == 0) or c in label_cols
            align = WD_ALIGN_PARAGRAPH.CENTER if (c in center_cols or (header and r == 0 and c > 0)) else None
            _cell_text(cell, value, bold=bold, align=align)
    _set_widths(table, widths)
    _keep_rows_together(table)
    keep_table_together(table)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def patient_box(doc: Document, sex: str, clinical: str, lmp: bool) -> None:
    """
    Patient details. `clinical` is either a {{placeholder}} or the form's fixed
    clinical-data text.
    """
    w = [1.3, 2.45, 1.15, CONTENT_W - 1.3 - 2.45 - 1.15]
    table = doc.add_table(rows=4, cols=4)
    table.style = "Table Grid"
    table.autofit = False
    rows = [
        ["Patient Name", "{{patient_name}}", "Date", "{{date}}"],
        ["Age / Sex", "{{age}} Y / " + sex, "Patient ID", "{{patient_id}}"],
        ["Referred by", "{{ref_by}}", "LMP" if lmp else "", "{{lmp}}" if lmp else ""],
        ["Clinical details", clinical, "", ""],
    ]
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            cell = table.rows[r].cells[c]
            cell.width = Inches(w[c])
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _cell_text(cell, value, bold=c in (0, 2))
    _set_widths(table, w)
    # Clinical details spans the row; without LMP so does "Referred by"
    table.rows[3].cells[1].merge(table.rows[3].cells[3])
    if not lmp:
        table.rows[2].cells[1].merge(table.rows[2].cells[3])
    _tidy_merged(table)
    _keep_rows_together(table)
    keep_table_together(table)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def _tidy_merged(table) -> None:
    """Merging keeps the empty paragraphs of absorbed cells; drop them."""
    for row in table.rows:
        for cell in row.cells:
            paragraphs = cell.paragraphs
            for p in paragraphs[1:]:
                if not p.text.strip():
                    p._p.getparent().remove(p._p)


def findings(doc: Document, items: list[tuple[str, str | list]]) -> None:
    """
    Label / description pairs, aligned in a borderless two-column table so
    the descriptions line up. A description may be a list of lines.
    """
    label_w = 1.75
    table = doc.add_table(rows=len(items), cols=2)
    table.autofit = False
    for r, (label, text) in enumerate(items):
        left, right = table.rows[r].cells
        left.width = Inches(label_w)
        right.width = Inches(CONTENT_W - label_w)
        _cell_text(left, label + ":" if label else "", bold=True, size=BODY_PT)
        _cell_text(right, text, size=BODY_PT)
    _set_widths(table, [label_w, CONTENT_W - label_w])
    _keep_rows_together(table)


def impression(doc: Document, lines: list[str], adv: str = "") -> None:
    heading(doc, "Impression")
    for line in lines or [""]:
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(line).bold = True
    if adv:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(4)
        p.add_run("Adv: ").bold = True
        p.add_run(adv).bold = True


def note(doc: Document, lines: list[str], label: str = "") -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    if label:
        r = p.add_run(label)
        r.bold = True
        r.font.size = Pt(NOTE_PT)
    for i, line in enumerate(lines):
        if i or label:
            p.add_run().add_break()
        p.add_run(line).font.size = Pt(NOTE_PT)


def declaration(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.keep_with_next = True
    r = p.add_run("DECLARATION OF DOCTOR/PERSON CONDUCTING ULTRASONOGRAPHY / IMAGE SCANNING")
    r.bold = True
    r.font.size = Pt(NOTE_PT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.keep_with_next = True
    p.add_run(text).font.size = Pt(NOTE_PT)


def signature(doc: Document) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_before = Pt(36)
    p.paragraph_format.keep_with_next = True
    p.add_run("{{doctor_name}}").bold = True
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run("{{doctor_qual}}")


def pairs(doc: Document, rows: list[list[str]]) -> None:
    """Measurement table: Parameter | Value | Parameter | Value."""
    w = [1.95, 1.43, 1.95, CONTENT_W - 1.95 - 1.43 - 1.95]
    grid_table(doc, [["Parameter", "Value", "Parameter", "Value"]] + rows, w,
               header=True, label_cols=(0, 2), center_cols=(1, 3))


def dating(doc: Document, rows: list[list[str]]) -> None:
    """Gestational age / EDD table: Parameter | By scan | By LMP."""
    w = [2.2, 2.3, CONTENT_W - 2.2 - 2.3]
    grid_table(doc, [["Parameter", "By scan", "By LMP"]] + rows, w,
               header=True, center_cols=(1, 2))


def doppler(doc: Document, rows: list[list[str]], intro: str = "") -> None:
    if intro:
        doc.add_paragraph(intro)
    w = [3.0, 1.6]
    grid_table(doc, [["Artery", "PI"]] + rows, w, header=True, center_cols=(1,))


GA_SCAN = "{{aua_weeks}} weeks {{aua_days}} days"
GA_LMP = "{{ga_lmp_weeks}} weeks {{ga_lmp_days}} days"
STANDARD_NOTE = (
    "This is only a radiological impression and not a diagnosis and has its "
    "limitations. Therefore, it should be interpreted in correlation with "
    "clinical and/or pathological findings."
)
DECLARATION_F = (
    "I, {{doctor_name}}, declare that while conducting ultrasonography / image "
    "scanning on Mrs. {{patient_name}}, I have neither detected nor disclosed "
    "the sex of her foetus to anybody in any manner."
)


# ---------------------------------------------------------------------------
# The seven forms
# ---------------------------------------------------------------------------

def early_pregnancy() -> Document:
    doc = new_doc()
    title(doc, "EARLY PREGNANCY SCAN")
    patient_box(doc, "F", "{{clinical_details}}", lmp=True)
    heading(doc, "Measurements")
    dating(doc, [
        ["CRL", "{{crl}} cm", "-"],
        ["Gestational age", "{{ga_scan_weeks}} weeks {{ga_scan_days}} days", GA_LMP],
        ["EDD", "{{edd_scan}}", "{{edd_lmp}}"],
        ["Foetal heart rate", "{{fhr}} BPM", "-"],
    ])
    heading(doc, "Findings")
    findings(doc, [
        ("Uterus", "Gravid uterus. No e/o focal lesions."),
        ("Gestational sac", "Seen."),
        ("Embryo", "Single in number."),
        ("Yolk sac", "Seen."),
        ("Cardiac activity", "Good ({{fhr}} BPM)."),
        ("Cervix", "Length {{cervix_length}} cm. Internal os closed."),
        ("Ovaries & adnexa", "Normal."),
    ])
    impression(doc, [
        "Single live intrauterine gestation corresponding to ~{{ga_scan_weeks}} weeks "
        "{{ga_scan_days}} days according to scan. FHR - {{fhr}} BPM.",
    ], adv="NT scan at 11-14 weeks.")
    declaration(doc, DECLARATION_F)
    signature(doc)
    return doc


def nt_scan() -> Document:
    doc = new_doc()
    title(doc, "OBSTETRIC ULTRASOUND REPORT (NT SCAN)")
    patient_box(doc, "F", "{{clinical_details}}", lmp=True)
    heading(doc, "Gestational age")
    dating(doc, [
        ["Gestational age", GA_SCAN, GA_LMP],
        ["EDD", "{{edd_scan}}", "{{edd_lmp}}"],
    ])
    heading(doc, "Biometry and aneuploidy markers")
    pairs(doc, [
        ["CRL", "{{crl}} cm", "Foetal heart rate", "{{fhr}} BPM"],
        ["Nuchal translucency", "{{nt}} mm", "Nasal bone", "{{nasal_bone}} mm"],
        ["Ductus venosus flow", "Normal 'a' wave", "", ""],
    ])
    heading(doc, "Findings")
    findings(doc, [
        ("Foetus", "Single live foetus."),
        ("Liquor", "Adequate."),
        ("Placenta", "Located in posterior, grade 1. Lower limit of placenta is seen "
                     "well away from the internal OS."),
        ("Cervix", "Length {{cervix_length}} cm, internal OS closed."),
        ("Ovaries & adnexa", "Normal."),
    ])
    heading(doc, "Uterine artery Doppler")
    doppler(doc, [
        ["Right uterine artery", "{{doppler_right_pi}}"],
        ["Left uterine artery", "{{doppler_left_pi}}"],
    ])
    heading(doc, "First trimester screening for Down's syndrome")
    grid_table(doc, [
        ["Maternal age risk", "1 in {{maternal_age_risk}}"],
        ["Risk estimate (foetus)", "1 in {{nt_risk}}"],
    ], [3.0, 1.6], center_cols=(1,))
    impression(doc, [
        "Single live intrauterine gestation corresponding to " + GA_SCAN +
        " according to scan with good FHR, normal NT and nasal bone.",
    ], adv="Anomaly scan at 20 weeks.")
    note(doc, [
        "Foetal heart, spine, face and kidneys cannot be well assessed at this stage "
        "of pregnancy. These regions can be assessed in the 20 to 24 weeks scan.",
        "Down's syndrome can't be diagnosed on the basis of USG alone. The risk ratio "
        "indicates risk rates; it is not definitive testing.",
        "Detection of Down's syndrome by: first trimester NT only - 64 to 70%; first "
        "trimester combined (NT + maternal blood test) - 80 to 85%; sequential screening "
        "(combined quadruple 15-19 weeks + genetic sonogram at 18-20 weeks) - 95%; "
        "maternal blood test for cell free foetal DNA - 99%.",
        "Invasive testing (CVS/amniocentesis), which is a definitive test, has a "
        "procedure related risk of about 1:200.",
        "This has been explained to the patient and attendant.",
    ], label="Note:")
    declaration(doc, DECLARATION_F)
    signature(doc)
    return doc


def anomaly_scan() -> Document:
    doc = new_doc()
    title(doc, "ANOMALY SCAN")
    patient_box(doc, "F", "{{clinical_details}}", lmp=True)
    heading(doc, "Foetus")
    doc.add_paragraph("Single live foetus with {{foetal_lie}} lie. Foetal cardiac "
                      "activity and movements good, FHR: {{fhr}} BPM.")
    heading(doc, "Gestational age")
    dating(doc, [
        ["Gestational age", GA_SCAN, GA_LMP],
        ["EDD", "{{edd_scan}}", "{{edd_lmp}}"],
    ])
    heading(doc, "Biometric measurements")
    pairs(doc, [
        ["BPD", "{{bpd}} cm", "HC", "{{hc}} cm"],
        ["AC", "{{ac}} cm", "FL", "{{fl}} cm"],
        ["HL", "{{hl}} cm", "UL", "{{ul}} cm"],
        ["RL", "{{rl}} cm", "TL", "{{tl}} cm"],
        ["FIB", "{{fib}} cm", "Foot length", "{{foot_length}} cm"],
        ["EFW", "{{efw}} g +/- {{efw_error}} g", "FL / AC", "{{fl_ac_ratio}} %"],
    ])
    heading(doc, "Other measurements")
    pairs(doc, [
        ["Nasal bone length", "{{nasal_bone_length}} mm", "Nuchal fold thickness", "{{nuchal_fold}} mm"],
        ["Trans cerebellar diameter", "{{tcd}} cm", "Cisterna magna", "{{cisterna_magna}} cm"],
        ["Lateral ventricular atrium", "{{lvta}} cm", "", ""],
    ])
    heading(doc, "Foetal anatomy")
    findings(doc, [
        ("Foetal head", ["Foetal calvaria appears normal.",
                         "Thalami, cavum septum, ventricular system appear normal.",
                         "Posterior fossa structures appear to be normal up to visible extent."]),
        ("Foetal face", ["Orbits appear to be normal up to visible extent.",
                         "No E/O cleft lip."]),
        ("Foetal thorax", "Both lungs seen."),
        ("Foetal heart", [
            "Normal sinus rhythm. Situs solitus. Cardiac size and axis appear normal.",
            ("Four chamber view:", "Both the atria and ventricles appear to be normal in size. "
             "2 pulmonary veins seen draining into the left atrium. Crux visualized. "
             "AV valve insertion seen normal. Interventricular septum seen intact. "
             "Foramen ovale seen with flow from right to left atrium. Mitral valve and "
             "tricuspid valve appear normal. Flow across the valves: laminar flow."),
            ("LVOT:", "Aortic valve appears normal. Flow across the valve: laminar flow. "
             "Septo-aortic continuation and septo-mitral continuation seen."),
            ("RVOT:", "Pulmonary valve appears normal. Main pulmonary artery seen, appears normal."),
            ("3 vessel view:", "Pulmonary artery, aorta and right SVC seen. Spatial alignment "
             "and size of the vessels appropriate."),
            ("3 vessel trachea view:", "Ductal arch and transverse aortic arch seen and normal. "
             "Spatial alignment and size of the vessels: normal. Flow in the vessels: laminar flow."),
        ]),
        ("Foetal abdomen", ["Situs solitus noted. Stomach bubble seen.",
                            "Both kidneys well visualized. Urinary bladder seen.",
                            "Anterior abdominal wall appears to be normal.",
                            "Umbilical cord insertion site appears to be normal."]),
        ("Foetal limbs", ["Visualized extent of upper and lower limbs appear normal.",
                          "No evidence of focal limb abnormalities up to visible extent."]),
        ("Foetal spine", "Foetal spine appears normal in both long and transverse scans "
                         "up to visible extent."),
        ("Liquor", "Adequate."),
        ("Placenta", "Located in posterior, grade 1 to 2. Lower limit of placenta situated "
                     "well away from the internal OS."),
        ("Cervix", "Length {{cervix_length}} cm, internal OS closed."),
        ("Umbilical cord", "Three vessel cord. No cord around the neck noted at present scan."),
    ])
    heading(doc, "Uterine artery Doppler")
    doppler(doc, [
        ["Right uterine artery", "{{doppler_right_pi}}"],
        ["Left uterine artery", "{{doppler_left_pi}}"],
    ])
    impression(doc, [
        "Single live intrauterine gestation corresponding to ~" + GA_SCAN +
        " by scan and " + GA_LMP + " by LMP.",
        "No other obvious structural congenital abnormalities for this gestation.",
        "Basic cardiac screening appears to be normal for this gestation.",
        "Uterine artery Doppler study shows normal flow.",
    ], adv="Follow up scan at 30 weeks.")
    note(doc, [
        "Down's syndrome can't be diagnosed on the basis of USG alone.",
        "Detection of Down's syndrome by: sequential screening (combined quadruple "
        "15-19 weeks + genetic sonogram at 18-20 weeks) - 95%; maternal blood test for "
        "cell free foetal DNA - 99%.",
        "Invasive testing (CVS/amniocentesis), which is a definitive test, has a "
        "procedure related risk of about 1:200.",
        "This has been explained to the patient and attendant.",
        "# Ultrasound can't detect all congenital anomalies; the detection rate of "
        "congenital anomalies by anomaly scan is 60 to 80%.",
        "Please note: all abnormalities and genetic syndromes cannot be ruled out by "
        "ultrasound examination; ultrasound examination has its own limitations. Some "
        "abnormalities evolve as the gestation advances; the detection rate of "
        "abnormality depends on gestational age of the foetus, foetal position, tissue "
        "penetration of sound waves and patient body habitus.",
    ], label="Note:")
    declaration(doc, DECLARATION_F)
    signature(doc)
    return doc


def growth_scan() -> Document:
    doc = new_doc()
    title(doc, "OBSTETRIC ULTRASOUND REPORT")
    patient_box(doc, "F", "{{clinical_details}}", lmp=True)
    findings(doc, [
        ("Type of study", "Growth assessment and biophysical profile only."),
        ("Route", "Trans abdominal."),
        ("Foetus", "Single live foetus with cephalic presentation."),
    ])
    heading(doc, "Gestational age")
    dating(doc, [
        ["Gestational age", GA_SCAN, GA_LMP],
        ["EDD", "{{edd_scan}}", "{{edd_lmp}}"],
    ])
    heading(doc, "Biometric measurements")
    pairs(doc, [
        ["BPD", "{{bpd}} cm", "HC", "{{hc}} cm"],
        ["AC", "{{ac}} cm", "FL", "{{fl}} cm"],
        ["EFW", "{{efw}} g +/- {{efw_error}} g", "Foetal heart rate", "{{fhr}} BPM"],
        ["AFI", "{{afi}} cm", "", ""],
    ])
    heading(doc, "Findings")
    findings(doc, [
        ("Biophysical profile", ["Foetal maturity: femoral ossification centre noted and tibial appearing.",
                                 "Foetal tone and movements are good.",
                                 "Foetal breathing movements good.",
                                 "Foetal cardiac activity good. FHR: {{fhr}} BPM.",
                                 "U/S biophysical scoring 8/8."]),
        ("Liquor", "AFI: {{afi}} cm."),
        ("Placenta", "Located in posterior, grade 3. Lower limit of placenta situated well "
                     "away from the internal OS."),
        ("Cervix", "Visualized cervix measuring {{cervix_length}} cm."),
        ("Umbilical cord", "No E/O cord around the neck noted at the time of scanning."),
    ])
    heading(doc, "Doppler study")
    doppler(doc, [
        ["Right uterine artery", "{{doppler_right_pi}}"],
        ["Left uterine artery", "{{doppler_left_pi}}"],
        ["Umbilical artery", "{{doppler_umbilical_pi}}"],
        ["MCA flow", "{{doppler_mca_pi}}"],
        ["CPR", "{{cpr}}"],
    ])
    impression(doc, [
        "Single live intrauterine gestation corresponding to " + GA_SCAN +
        " by scan and " + GA_LMP + " by LMP.",
        "Doppler study was normal at present scan.",
    ])
    note(doc, [
        "Foetal anatomy (limbs, spine, cardiac, etc.) can't be made out in detail at this "
        "stage due to advanced gestational age and unaccommodating foetal position; the "
        "ideal time to study the foetal anatomy is 20 to 22 weeks. This has been "
        "explained to the patient and attendant.",
        "# All congenital anomalies can't be detected by antenatal ultrasound.",
    ], label="Note:")
    declaration(doc, DECLARATION_F)
    signature(doc)
    return doc


def follicular_study() -> Document:
    doc = new_doc()
    title(doc, "PELVIC ULTRASOUND REPORT (FOLLICULAR STUDY)")
    patient_box(doc, "F", "c/o anxious to conceive.", lmp=False)
    heading(doc, "Findings")
    findings(doc, [
        ("Urinary bladder", "Distended."),
        ("Uterus", "Anteverted, measuring {{uterus_size}} cm."),
        ("Cervix", "Normal."),
        ("Right ovary", "Measuring {{right_ovary_size}} cm."),
        ("Left ovary", "Measuring {{left_ovary_size}} cm."),
    ])
    heading(doc, "Follicular monitoring")
    w = [0.8, 1.45, 1.6, 1.6, CONTENT_W - 0.8 - 1.45 - 1.6 - 1.6]
    grid_table(doc, [["Day", "Endometrial thickness (mm)", "Follicles - right ovary",
                      "Follicles - left ovary", "Free fluid"]]
               # First row: this scan (endometrium from the scanner); the rest for follow-up visits
               + [["", "{{endometrium_mm}}", "", "", ""]] + [[""] * 5 for _ in range(9)],
               w, header=True, label_cols=(), center_cols=(0, 1, 2, 3, 4))
    impression(doc, [])
    note(doc, [STANDARD_NOTE], label="Note: ")
    signature(doc)
    return doc


def _abdomen(sex: str, pelvis: list[tuple[str, str]]) -> Document:
    doc = new_doc()
    title(doc, "ABDOMINO-PELVIC ULTRASOUND REPORT")
    patient_box(doc, sex, "{{clinical_data}}", lmp=False)
    heading(doc, "Findings")
    kidney = ("Normal in size, measuring {} cm, shape, position and echogenicity. "
              "No calculus seen. Pelvicalyceal system is not dilated.")
    findings(doc, [
        ("Liver", "Normal in size ({{liver_size}} cm), with normal parenchymal echogenicity, "
                  "however not obscuring peri-portal or diaphragmatic echogenicity. Biliary "
                  "radicles are not dilated. No obvious focal lesions seen. Portal vein is normal."),
        ("Gall bladder", "Distended, wall appears normal. CBD is normal."),
        ("Pancreas", "Head appears normal, body and tail obscured."),
        ("Spleen", "Appears normal ({{spleen_size}} cm) in size and echotexture. No focal lesion seen."),
        ("Right kidney", kidney.format("{{right_kidney_size}}")),
        ("Left kidney", kidney.format("{{left_kidney_size}}")),
        ("Urinary bladder", "Distended."),
        *pelvis,
        ("Free fluid", "No free fluid noted at the time of scan."),
        ("Bowel loops", "Visualized bowel loops show peristalsis."),
    ])
    impression(doc, [])
    note(doc, [STANDARD_NOTE], label="Note: ")
    signature(doc)
    return doc


def abdomen_pelvis_female() -> Document:
    return _abdomen("F", [
        ("Uterus", "Anteverted, measuring {{uterus_size}} cm, endometrium thickness {{endometrium_mm}} mm."),
        ("Right ovary", "Measuring {{right_ovary_size}} cm."),
        ("Left ovary", "Measuring {{left_ovary_size}} cm."),
    ])


def abdomen_pelvis_male() -> Document:
    return _abdomen("M", [
        ("Prostate", "Normal in size and echotexture, measuring {{prostate_size}} cm."),
    ])


FORMS = {
    "early_pregnancy": early_pregnancy,
    "nt_scan": nt_scan,
    "anomaly_scan": anomaly_scan,
    "growth_scan": growth_scan,
    "follicular_study": follicular_study,
    "abdomen_pelvis_female": abdomen_pelvis_female,
    "abdomen_pelvis_male": abdomen_pelvis_male,
}


def main() -> None:
    for name, build in FORMS.items():
        path = TEMPLATE_DIR / f"{name}.docx"
        build().save(path)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()

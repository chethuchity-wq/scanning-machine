---
title: Ultrasound DICOM Reporting Pipeline
description: Automated measurement extraction, scan classification, and clinical report generation from ultrasound DICOM files.
ms.date: 2026-07-02
ms.topic: overview
---

## Overview

Automated measurement extraction and clinical report generation from ultrasound DICOM files. Connects to an Orthanc DICOM server, extracts radiologist measurements from Structured Reports and burned-in image annotations (OCR), compares against normal reference ranges, and generates both PDF summary reports and doctor-fillable Word (.docx) reports.

## Features

- **Orthanc Integration** — Pull studies directly from your Orthanc DICOM server via REST API. Watch for new scans and auto-generate reports.
- **SR Extraction** — Parse DICOM Structured Reports for high-quality numeric measurements (liver size, kidney length, etc.)
- **OCR Fallback** — Read burned-in text annotations from ultrasound pixel data using Tesseract OCR
- **Scan Type Classification** — Automatically identify the ultrasound scan type (early pregnancy, NT scan, anomaly scan, growth scan, follicular study, abdomen/pelvis) from DICOM metadata, OCR text, or measurement fingerprinting
- **Normal Range Comparison** — Adult reference values for liver, kidneys, spleen, gallbladder, pancreas, aorta, thyroid, and more
- **PDF Report Generation** — Clinical summary reports with measurements table, color-coded status (Normal/HIGH/LOW), findings section, and signature area
- **Word (.docx) Report Generation** — Scan-specific fillable report templates pre-populated with objective measurements; impression and clinical findings are always left blank for the doctor to complete
- **Local Folder Processing** — Works with USB/network exports without requiring Orthanc connection

## Architecture

```
Orthanc Server (or local folder)
        │
        ▼
┌──────────────────┐
│  pipeline.py     │  ← Orchestrator (watch/study/folder/list/search)
└──────────────────┘
        │
        ├──► orthanc_client.py       — REST API client
        ├──► extract_measurements.py — SR + private tag extraction
        ├──► ocr_extract.py          — Tesseract OCR on pixel data
        ├──► normal_ranges.py        — Reference range database
        ├──► report_generator.py     — PDF output (fpdf2)
        ├──► scan_classifier.py      — 3-layer scan type auto-detection
        ├──► fill_report.py          — Word (.docx) report generation
        ├──► image_extract.py        — DICOM pixel data → PNG for report embedding
        └──► webapp/db.py            — records each report to the dashboard DB

webapp/main.py (dashboard, separate process) ──► reads webapp/db.py + reports/
```

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Tesseract OCR (for OCR module)

Download and install from: https://github.com/UB-Mannheim/tesseract/wiki

After installation, if `tesseract` is not in your system PATH, set the path in `config.py`:

```python
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

### 3. Configure

Edit `config.py` with your environment:

```python
# Orthanc server
ORTHANC_URL = "http://192.168.1.100:8042"
ORTHANC_USERNAME = "orthanc"
ORTHANC_PASSWORD = "orthanc"

# Clinic info (shown on PDF reports)
CLINIC_NAME = "Ganesh Healthcare"
CLINIC_ADDRESS = "Your Address"
CLINIC_PHONE = "+91-XXXXXXXXXX"
```

## Usage

### Process a local DICOM folder (no Orthanc needed)

```bash
python pipeline.py folder "D:\DICOM_Export"
```

### List studies on Orthanc server

```bash
python pipeline.py list
python pipeline.py list --limit 50
```

### Process a specific study

```bash
python pipeline.py study <orthanc-study-id>
```

### Search for a patient

```bash
python pipeline.py search --name "Kumar*"
python pipeline.py search --name "Raj*" --date "20260601-20260630"
```

### Watch mode (auto-process new scans)

```bash
python pipeline.py watch
```

This runs continuously, polling Orthanc every 10 seconds (configurable). When a new study becomes stable (all images received), it automatically extracts measurements and generates a PDF report.

### Original Excel export (still works)

```bash
python read_dicom.py --input "D:\DICOM_Export" --output "measurements.xlsx"
```

## Dashboard (worklist + settings)

A small web dashboard runs alongside the pipeline so clinic staff can browse and download generated reports, and edit clinic display info, without touching files or the command line.

```bash
uvicorn webapp.main:app --host 0.0.0.0 --port 8000
```

Or, via Docker, it's already wired up as the `us-webapp` service in `docker-compose.yml` (started automatically by `deploy.bat`) at **http://localhost:8080**.

On first visit, it prompts you to create the first admin account (there's no default password).

**Single-PC clinic, no login:** set `DASHBOARD_LOGIN_REQUIRED = False` in `config_local.py`
and start it with `--host 127.0.0.1`. There are then no accounts or login page, and the
dashboard refuses every connection that doesn't come from the PC itself. Every report `pipeline.py` generates is automatically recorded and shows up in the worklist. Orthanc connection settings are still edited in `config_local.py` (a service restart is needed for those to apply); clinic name/address/phone shown on PDF reports can be edited live from the Settings page.

## Output

Each scan gets one report: the Word report (see below), shown as one row in the
dashboard worklist. The worklist shows one study date per page (today by
default, with previous/next day buttons and a date picker) and numbers the
day's scans 1, 2, 3... in the order they arrived.

A PDF is made only when the PDF button is clicked: Microsoft Word converts the
Word report (`docx_pdf.py`), saving it next to it in `reports/filled/`, and
converts it again whenever the Word report has been edited since, so the two
always print the same. This needs Microsoft Word installed on the PC.

Only when no Word report can be made (scan type not identified) is a
measurements-only summary PDF built instead, saved to `reports/`. It includes:

- Patient demographics
- Measurements table with values, units, and normal ranges
- Color-coded status: **Normal** (green), **HIGH** (red), **LOW** (orange)
- Findings section with flagged abnormalities
- Signature area for sonographer and radiologist

## Measurement Extraction Priority

1. **Structured Reports (SR)** — Highest quality. These contain caliper measurements taken by the sonographer during the scan.
2. **DICOM Private Tags** — Vendor-specific metadata (Philips, GE, etc.)
3. **OCR** — Fallback. Reads text burned into the ultrasound image pixels.

If SR data is available, OCR is skipped (SR is definitive).

## Normal Ranges Included

| Organ | Measurements |
|-------|-------------|
| Liver | Span, length, right/left lobe, caudate |
| Gallbladder | Wall thickness, length, CBD, CHD |
| Spleen | Length |
| Kidneys | Length (R/L), cortical thickness, RI |
| Pancreas | Head, body, tail, pancreatic duct |
| Aorta | Diameter |
| IVC | Diameter |
| Thyroid | Lobe dimensions, isthmus |
| Portal Vein | Diameter, velocity |
| Heart (echo) | EF, FS, IVS, LVPW, LA |

Reference values are based on standard adult radiology textbooks. Pediatric and obstetric ranges are not included (can be added to `normal_ranges.py`).

## Word Report Generation

`fill_report.py` generates scan-specific `.docx` reports directly from DICOM data. Each report is pre-filled with objective measurements extracted from the scan; the **Impression** section and all clinical assessment fields are always left blank for the doctor to complete in Word.

### Supported report types

| Scan type | Report |
|---|---|
| Early pregnancy | Dating, crown-rump length, cardiac activity |
| NT scan | Nuchal translucency, nasal bone, fetal biometry |
| Anomaly scan | Full fetal anatomy survey |
| Growth scan | Biometry, EFW, placenta, liquor |
| Follicular study | Daily follicle tracking table |
| Abdomen/Pelvis — Female | Liver, kidneys, uterus, ovaries, free fluid |
| Abdomen/Pelvis — Male | Liver, kidneys, prostate, free fluid |

Reports are saved to `reports/filled/` and named `<PatientName>_<scan_type>_<date>.docx`.

### Clinic templates

Each report is built from the clinic's own Word form in `templates/<scan_type>.docx`
(e.g. `templates/early_pregnancy.docx`). Blanks are marked `{{field}}` — `{{crl}}`,
`{{ga_scan_weeks}}`, `{{doctor_name}}` and so on — and filled from the scan; a
field with no value is left blank for the doctor. All other wording (standard
normal findings, notes, advice) prints exactly as written in the form.

The forms are laid out by `tools/build_templates.py`: patient details box,
measurement and Doppler tables, aligned findings, impression, PCPNDT declaration
and doctor's signature, in black and white with a 1.5" top margin for the
clinic's pre-printed letterhead. Re-running it overwrites `templates/`.

To change a report's wording, edit `tools/build_templates.py` and re-run it (or
edit the template in Word, keeping the `{{...}}` markers intact). A scan type without a template falls back to the built-in layout
in `fill_report.py`. Dates print as DD/MM/YYYY; the doctor's name and
qualification come from the dashboard Settings page.

### Scan type classification

`scan_classifier.py` detects the scan type automatically, in this order:

0. **Exam type chosen on the scanner** — the Philips Affiniti sends it as
   `CommentsOnThePerformedProcedureStep` (0040,0280: `OB`, `Abdomen`) and the
   preset as `ProcessingFunction` (0018,5020: `OB_GENERAL`, `ABD_GENERAL`,
   `GYN_PELVIC`, `GYN_FERTILITY`...). `GYN_FERTILITY` → follicular study, other
   `GYN_*` → abdomen & pelvis (female), `Abdomen` → abdomen & pelvis by patient
   sex (female, flagged for review, when no sex was entered). `OB` → form by
   gestational age (scanner GA, else Hadlock from FL/BPD): under 11 weeks early
   pregnancy, 11–13 NT, 14–27 anomaly, 28+ growth (`OB_FORM_BY_GA_WEEKS`).
1. **DICOM metadata** — `StudyDescription`, `ProtocolName`, `SeriesDescription`
2. **OCR** — Tesseract reads burned-in text from the image pixels
3. **Measurement fingerprinting** — Infers type from which measurements are present (e.g. NT + CRL → NT scan)

## File Structure

```
scanning-machine/
├── config.py                 # Pipeline configuration
├── orthanc_client.py         # Orthanc REST API client
├── extract_measurements.py   # SR + private tag extraction
├── ocr_extract.py            # OCR burned-in annotation extraction
├── normal_ranges.py          # Normal reference ranges database
├── report_generator.py       # PDF report generation
├── scan_classifier.py        # Scan type auto-detection (3-layer)
├── fill_report.py            # Word (.docx) report generation
├── image_extract.py          # DICOM pixel data → PNG for report embedding
├── pipeline.py               # Main entry point / orchestrator
├── read_dicom.py             # Original Excel-based extractor
├── webapp/                   # Dashboard (worklist + settings web UI)
│   ├── main.py                # FastAPI app / routes
│   ├── db.py                  # SQLite models (clinics, users, studies, reports)
│   ├── auth.py                # Password hashing
│   └── templates/, static/    # Jinja2 templates + CSS
├── config_local.example.py   # Template for machine-specific secrets (copy to config_local.py)
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## Requirements

- Python 3.10+
- Orthanc DICOM server (for server modes; not needed for local folder processing)
- Tesseract OCR (for OCR fallback; pipeline works without it using SR data only)
- Scanner that exports DICOM with Structured Reports (most modern ultrasound machines do)

## Notes

- The OCR module is a **fallback**. Best results come from Structured Reports. Ensure your sonographers save measurements (caliper/trace) during the scan.
- Normal ranges are for **adults only**. Do not use for pediatric or obstetric scans without updating `normal_ranges.py`.
- Reports are auto-generated aids. **Radiologist review is mandatory** before clinical use.
- The Orthanc `watch` mode uses the Changes API. Ensure your Orthanc instance has `StableStudy` events enabled (default behavior).


Quickest path for you
Since your scanning machines are Windows and likely don't have Docker:

Install Python on the target machine
Copy the folder over (USB, network share, whatever)
Double-click install.bat
Update the Orthanc IP in config.py
Run run.bat watch — it starts processing scans automatically
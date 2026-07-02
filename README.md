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
        └──► fill_report.py          — Word (.docx) report generation
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

## Output

PDF reports are saved to the `reports/` directory (configurable in `config.py`). Each report includes:

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

### Scan type classification

`scan_classifier.py` detects the scan type automatically using three layers:

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
├── pipeline.py               # Main entry point / orchestrator
├── read_dicom.py             # Original Excel-based extractor
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
"""
Word report -> PDF, using Microsoft Word itself.

The PDF is always a conversion of the .docx, never built separately, so the
two print identically. Word is driven through PowerShell COM automation (no
extra Python packages) in a subprocess with a timeout, so a stuck Word can
never hang the pipeline or the dashboard.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TIMEOUT_SECONDS = 120

# 17 = wdFormatPDF. Opened read-only so a report the doctor has open in Word
# still converts; DisplayAlerts off so no dialog can block a background run.
# Paths arrive in environment variables, so no quoting of file names.
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
try {
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($env:REPORT_DOCX, $false, $true, $false)
    try { $doc.SaveAs2($env:REPORT_PDF, 17) } finally { $doc.Close($false) }
} finally {
    $word.Quit()
}
"""


def pdf_path_for(docx_path: str | Path) -> Path:
    """Where the PDF of a Word report lives: next to it, same name."""
    return Path(docx_path).with_suffix(".pdf")


def is_stale(docx_path: str | Path) -> bool:
    """True if the PDF is missing or older than its Word report (doctor edited it)."""
    docx_path = Path(docx_path)
    pdf = pdf_path_for(docx_path)
    return not pdf.exists() or pdf.stat().st_mtime < docx_path.stat().st_mtime


def convert(docx_path: str | Path) -> Path | None:
    """
    Convert a Word report to PDF next to it. Returns the PDF path, or None if
    Word is unavailable or fails (the reason is printed to the log).
    """
    docx_path = Path(docx_path).resolve()
    pdf = pdf_path_for(docx_path)
    # An older PDF may already be there; success means Word rewrote it
    before = pdf.stat().st_mtime if pdf.exists() else None
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", _SCRIPT],
            env={**os.environ, "REPORT_DOCX": str(docx_path), "REPORT_PDF": str(pdf)},
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  [PDF] Word conversion failed for {docx_path.name}: {e}")
        return None
    if result.returncode != 0 or not pdf.exists() or pdf.stat().st_mtime == before:
        print(f"  [PDF] Word conversion failed for {docx_path.name}: "
              f"{(result.stderr or result.stdout).strip()[:500]}")
        return None
    return pdf

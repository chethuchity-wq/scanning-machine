"""
DICOM Image Extraction for Report Embedding
=============================================
Converts DICOM ultrasound image pixel data into PNG bytes suitable for
embedding in the generated PDF and Word reports.

Usage:
    from image_extract import dicom_to_png_bytes

    png_bytes = dicom_to_png_bytes(ds)  # None if ds has no pixel data
"""

import io
from typing import Optional

import numpy as np
import pydicom
from PIL import Image


def dicom_to_png_bytes(ds: pydicom.Dataset) -> Optional[bytes]:
    """
    Convert a single DICOM instance's pixel data to PNG bytes for report
    embedding. For multi-frame instances (cine loops), only the first frame
    is used. Returns None for instances with no pixel data (e.g. SR) or
    that fail to decode.
    """
    if "PixelData" not in ds:
        return None

    try:
        arr = ds.pixel_array
    except Exception:
        return None

    # Multi-frame: take the first frame only.
    # Color multiframe: (frames, rows, cols, channels). Grayscale multiframe: (frames, rows, cols).
    num_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    if num_frames > 1 and arr.ndim >= 3:
        arr = arr[0]

    photometric = str(getattr(ds, "PhotometricInterpretation", "")).upper()

    if photometric.startswith("YBR"):
        try:
            from pydicom.pixel_data_handlers.util import convert_color_space
            arr = convert_color_space(arr, photometric, "RGB")
        except Exception:
            pass

    if photometric == "MONOCHROME1":
        arr = arr.max() - arr

    # Normalize to 8-bit for display.
    if arr.dtype != np.uint8:
        arr = arr.astype(np.float32)
        lo, hi = float(arr.min()), float(arr.max())
        if hi > lo:
            arr = (arr - lo) / (hi - lo) * 255.0
        else:
            arr = np.zeros_like(arr)
        arr = arr.astype(np.uint8)

    if arr.ndim == 2:
        image = Image.fromarray(arr, mode="L")
    elif arr.ndim == 3 and arr.shape[-1] == 3:
        image = Image.fromarray(arr, mode="RGB")
    elif arr.ndim == 3 and arr.shape[-1] == 4:
        image = Image.fromarray(arr, mode="RGBA").convert("RGB")
    else:
        return None

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


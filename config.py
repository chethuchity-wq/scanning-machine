"""
Pipeline Configuration
======================
Central configuration for the ultrasound DICOM reporting pipeline.
Update these values to match your environment.
"""

# ---------------------------------------------------------------------------
# Orthanc Server
# ---------------------------------------------------------------------------
ORTHANC_URL = "http://192.168.1.100:8042"  # Change to your Orthanc server IP
ORTHANC_USERNAME = "orthanc"                # Default Orthanc credentials
ORTHANC_PASSWORD = "orthanc"                # Change if you've set custom auth

# ---------------------------------------------------------------------------
# Output Paths
# ---------------------------------------------------------------------------
OUTPUT_DIR = "reports"              # Where generated PDF reports are saved
MEASUREMENTS_DIR = "measurements"   # Where Excel measurement files are saved
DICOM_CACHE_DIR = "dicom_cache"    # Temp folder for downloaded DICOM files

# ---------------------------------------------------------------------------
# Pipeline Settings
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS = 10          # How often to check Orthanc for new studies
STABLE_STUDY_TIMEOUT = 30           # Seconds to wait after last instance before processing
WATCH_STATE_FILE = "watch_state.json"  # Persists watch mode's position across restarts
MAX_REPORT_IMAGES = 6                # Max representative scan images embedded per report
HEARTBEAT_URL = ""                   # Dead-man's-switch ping URL (e.g. healthchecks.io) - see config_local.example.py

# ---------------------------------------------------------------------------
# Dashboard (webapp/)
# ---------------------------------------------------------------------------
DB_PATH = "data/app.db"                        # Worklist/clinic-settings database
SESSION_SECRET_FILE = "data/session_secret.txt"  # Auto-generated on first run

# ---------------------------------------------------------------------------
# OCR Settings
# ---------------------------------------------------------------------------
TESSERACT_CMD = None                # Set path if not in PATH, e.g. r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OCR_CONFIDENCE_THRESHOLD = 60       # Minimum OCR confidence (0-100) to accept a reading
OCR_REGIONS = {
    # Regions of the ultrasound image where annotations typically appear
    # Format: (x_start_pct, y_start_pct, width_pct, height_pct) as percentages of image size
    "top_left": (0.0, 0.0, 0.5, 0.12),
    "top_right": (0.5, 0.0, 0.5, 0.12),
    "bottom_left": (0.0, 0.85, 0.5, 0.15),
    "bottom_right": (0.5, 0.85, 0.5, 0.15),
    "right_panel": (0.75, 0.12, 0.25, 0.73),
}

# ---------------------------------------------------------------------------
# Report Settings
# ---------------------------------------------------------------------------
CLINIC_NAME = "Ganesh Healthcare"
CLINIC_ADDRESS = "Your Clinic Address Here"
CLINIC_PHONE = "+91-XXXXXXXXXX"
CLINIC_LOGO = None                  # Path to clinic logo PNG (optional)
REPORT_FONT = "Helvetica"

# ---------------------------------------------------------------------------
# Local overrides
# ---------------------------------------------------------------------------
# Machine-specific secrets/settings (real Orthanc credentials, real clinic
# info) live in config_local.py, which is gitignored and never touched by
# `git pull`. Copy config_local.example.py to config_local.py on each
# deployed machine and fill it in. See README for details.
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass

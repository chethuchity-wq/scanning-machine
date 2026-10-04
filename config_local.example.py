"""
Local Configuration Overrides (template)
==========================================
Copy this file to `config_local.py` on each deployed machine and fill in
the real values. `config_local.py` is gitignored, so `git pull` will never
overwrite or conflict with it — it's the one file safe to hold real
credentials in.

Only override the settings that differ from config.py's defaults; anything
you don't set here just keeps its default from config.py.
"""

# ---------------------------------------------------------------------------
# Orthanc Server
# ---------------------------------------------------------------------------
# ORTHANC_URL = "http://192.168.1.100:8042"
# ORTHANC_USERNAME = "orthanc"
# ORTHANC_PASSWORD = "change-me"

# ---------------------------------------------------------------------------
# Clinic info (shown on PDF reports)
# ---------------------------------------------------------------------------
# CLINIC_NAME = "Ganesh Healthcare"
# CLINIC_ADDRESS = "Your Clinic Address Here"
# CLINIC_PHONE = "+91-XXXXXXXXXX"
# CLINIC_LOGO = r"C:\path\to\logo.png"

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
# Single-PC clinic: no login, dashboard reachable only from this PC itself.
# DASHBOARD_LOGIN_REQUIRED = False

# ---------------------------------------------------------------------------
# Reporting doctor (Word reports - PCPNDT declaration + signature)
# ---------------------------------------------------------------------------
# Normally set on the dashboard's Settings page instead. These only seed a
# brand-new database.
# DOCTOR_NAME = "Dr. A.B. Name"
# DOCTOR_QUAL = "MBBS. MDRD."
# REFERRING_DEFAULT = "Dr. C.D. Name"

# ---------------------------------------------------------------------------
# Remote monitoring (dead-man's-switch heartbeat)
# ---------------------------------------------------------------------------
# If this machine goes offline (power loss, network down, watch process
# crashed), it can't be the one to tell you - so instead it pings an
# external free service every poll cycle, and THAT service alerts you the
# moment the pings stop. Setup (~2 minutes):
#   1. Sign up free at https://healthchecks.io (or self-host: https://github.com/healthchecks/healthchecks)
#   2. Create a check with a "Period" a bit longer than POLL_INTERVAL_SECONDS
#      (e.g. 2-3x it, so one slow poll doesn't false-alarm)
#   3. Set its notification channel to email / Telegram / whatever you'll
#      actually see, in their UI
#   4. Paste the check's ping URL below
# HEARTBEAT_URL = "https://hc-ping.com/your-check-uuid-here"

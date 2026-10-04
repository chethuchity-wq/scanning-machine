"""
Clinic setup - second half of setup.bat
=======================================
Run by setup.bat (as administrator, with the project's .venv python) after
dependencies are installed. Safe to re-run: every step is idempotent.

  1. config_local.py - asks for Orthanc + clinic details, edits the file in
     place so any other settings already in it (TESSERACT_CMD, ...) survive
  2. checks Orthanc answers with those credentials
  3. firewall rules (dashboard 8000; DICOM 4242 when Orthanc is local),
     limited to the clinic LAN and Tailscale
  4. disables sleep on AC power
  5. Tesseract (reads the values printed on the scan images): installed if
     missing, and its path saved in config_local.py
  6. Microsoft Word (turns the Word reports into PDFs for printing): checked,
     and prepared for use by the background tasks
  7. registers the "Ultrasound Pipeline" and "Ultrasound Dashboard"
     scheduled tasks (start at boot as SYSTEM, no time limit, restart on
     failure) and starts them
  8. Desktop shortcuts: the dashboard, and "Restart Ultrasound Services"
  9. prints the dashboard URLs and the first-login setup token
"""

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_LOCAL = ROOT / "config_local.py"
CONFIG_EXAMPLE = ROOT / "config_local.example.py"
SETUP_TOKEN_FILE = ROOT / "data" / "setup_token.txt"
DASHBOARD_PORT = 8000

TASKS = {
    "Ultrasound Pipeline": ROOT / "deploy" / "service_pipeline.bat",
    "Ultrasound Dashboard": ROOT / "deploy" / "service_dashboard.bat",
}

TESSERACT_VERSION = "5.4.0.20240606"
TESSERACT_URL = ("https://github.com/UB-Mannheim/tesseract/releases/download/"
                 f"v{TESSERACT_VERSION}/tesseract-ocr-w64-setup-{TESSERACT_VERSION}.exe")
TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

# Clinic LAN + Tailscale's address range. The dashboard is plain HTTP, so it
# must never be reachable from the internet (see DEPLOY.md, Part A).
FIREWALL_REMOTE = "LocalSubnet,100.64.0.0/10"


def step(msg):
    print(f"\n[*] {msg}")


def ok(msg):
    print(f"[OK] {msg}")


def warn(msg):
    print(f"[!] {msg}")


def ask(prompt, default="", secret_default=False):
    shown = "press Enter to keep current" if secret_default and default else default
    suffix = f" [{shown}]" if shown else ""
    answer = input(f"    {prompt}{suffix}: ").strip()
    return answer or default


def yes(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    answer = input(f"    {prompt} [{hint}]: ").strip().lower()
    return default if not answer else answer.startswith("y")


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def run_powershell(script):
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# 1-2. config_local.py + Orthanc check
# ---------------------------------------------------------------------------

def load_config():
    """Current effective config (config.py defaults + config_local.py)."""
    sys.path.insert(0, str(ROOT))
    for name in ("config", "config_local"):
        sys.modules.pop(name, None)
    import config
    return config


def set_config_values(values):
    """Set KEY = value lines in config_local.py, keeping everything else.

    An existing uncommented line is replaced; otherwise the commented example
    line is uncommented in place; otherwise the line is appended.
    """
    if CONFIG_LOCAL.exists():
        text = CONFIG_LOCAL.read_text(encoding="utf-8")
    else:
        text = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    for key, value in values.items():
        line = f"{key} = {value!r}"
        live = re.compile(rf"^{key}\s*=.*$", re.M)
        commented = re.compile(rf"^#\s*{key}\s*=.*$", re.M)
        if live.search(text):
            text = live.sub(lambda _: line, text, count=1)
        elif commented.search(text):
            text = commented.sub(lambda _: line, text, count=1)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    CONFIG_LOCAL.write_text(text, encoding="utf-8")


def check_orthanc(url, username, password):
    try:
        r = requests.get(url.rstrip("/") + "/system", auth=(username, password), timeout=5)
    except requests.RequestException as e:
        return False, f"cannot connect to {url} ({e.__class__.__name__})"
    if r.status_code == 401:
        return False, "Orthanc rejected the username/password"
    if not r.ok:
        return False, f"Orthanc answered HTTP {r.status_code}"
    info = r.json()
    return True, f"Orthanc {info.get('Version', '?')} at {url} (AE title {info.get('DicomAet', '?')})"


def configure():
    step("Clinic configuration (config_local.py)")
    first_time = not CONFIG_LOCAL.exists()
    cfg = load_config()

    if not first_time:
        reachable, msg = check_orthanc(cfg.ORTHANC_URL, cfg.ORTHANC_USERNAME, cfg.ORTHANC_PASSWORD)
        print(f"    Existing config: {cfg.CLINIC_NAME} | Orthanc {cfg.ORTHANC_URL}")
        if reachable:
            ok(msg)
            if not yes("Keep the existing configuration?"):
                first_time = True
        else:
            warn(msg)
            first_time = True

    if not first_time:
        return cfg

    print("    Press Enter to accept the value in [brackets].")
    # 127.0.0.1, not localhost: Windows tries IPv6 first for "localhost" (2 s per connection)
    url_default = "http://127.0.0.1:8042" if not CONFIG_LOCAL.exists() else cfg.ORTHANC_URL
    while True:
        url = ask("Orthanc URL", url_default)
        username = ask("Orthanc username", cfg.ORTHANC_USERNAME)
        password = ask("Orthanc password", cfg.ORTHANC_PASSWORD, secret_default=True)
        reachable, msg = check_orthanc(url, username, password)
        if reachable:
            ok(msg)
            break
        warn(msg)
        if not yes("Re-enter the Orthanc details?"):
            warn("Continuing anyway - reports will not be generated until Orthanc is reachable.")
            break
        url_default = url

    values = {"ORTHANC_URL": url, "ORTHANC_USERNAME": username, "ORTHANC_PASSWORD": password,
              "POLL_INTERVAL_SECONDS": 3}
    print("    Is the dashboard used only on this PC? Then it needs no login, and other")
    print("    computers cannot open it. Answer n if staff open it from other PCs.")
    values["DASHBOARD_LOGIN_REQUIRED"] = not yes(
        "Dashboard used only on this PC (no login)?", not getattr(cfg, "DASHBOARD_LOGIN_REQUIRED", True))
    print("    Clinic details printed on PDF reports:")
    values["CLINIC_NAME"] = ask("Clinic name", cfg.CLINIC_NAME)
    values["CLINIC_ADDRESS"] = ask("Clinic address", cfg.CLINIC_ADDRESS)
    values["CLINIC_PHONE"] = ask("Clinic phone", cfg.CLINIC_PHONE)
    print("    healthchecks.io ping URL - alerts you when this PC stops working (DEPLOY.md, Part I).")
    heartbeat = ask("Heartbeat URL (Enter to skip)", cfg.HEARTBEAT_URL)
    if heartbeat:
        values["HEARTBEAT_URL"] = heartbeat

    if password == "orthanc":
        warn("Orthanc is still using the default password 'orthanc' - change it in orthanc.json.")

    set_config_values(values)
    ok(f"Saved {CONFIG_LOCAL}")
    return load_config()


# ---------------------------------------------------------------------------
# 3-4. Firewall + power
# ---------------------------------------------------------------------------

def firewall_rule(name, port):
    subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                   capture_output=True)
    r = subprocess.run(
        ["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in",
         "action=allow", "protocol=TCP", f"localport={port}", f"remoteip={FIREWALL_REMOTE}"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        ok(f"Firewall: port {port} open to the clinic LAN and Tailscale ({name})")
    else:
        warn(f"Could not add firewall rule '{name}': {r.stdout.strip() or r.stderr.strip()}")


def setup_firewall(cfg):
    step("Firewall")
    if getattr(cfg, "DASHBOARD_LOGIN_REQUIRED", True):
        firewall_rule("Ultrasound Dashboard", DASHBOARD_PORT)
    else:
        ok("Dashboard is for this PC only - no firewall opening for it")
    if urlparse(cfg.ORTHANC_URL).hostname in ("localhost", "127.0.0.1"):
        # The ultrasound machine sends DICOM to this PC
        firewall_rule("Orthanc DICOM", 4242)


def setup_power():
    step("Power settings")
    # A sleeping PC receives no scans and cannot be reached remotely
    for setting in ("standby-timeout-ac", "hibernate-timeout-ac"):
        subprocess.run(["powercfg", "/change", setting, "0"], capture_output=True)
    ok("Sleep and hibernate disabled on mains power")


# ---------------------------------------------------------------------------
# 5-6. Tesseract + Word
# ---------------------------------------------------------------------------

def find_tesseract():
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    return TESSERACT_EXE if TESSERACT_EXE.exists() else None


def setup_tesseract():
    step("Tesseract (reads the values printed on the scan images)")
    exe = find_tesseract()
    if exe is None:
        print(f"    Not installed - downloading Tesseract {TESSERACT_VERSION} (about 50 MB)...")
        installer = Path(os.environ.get("TEMP", ".")) / "tesseract-setup.exe"
        r = subprocess.run(["curl.exe", "-L", "--fail", "--silent", "--show-error",
                            "-o", str(installer), TESSERACT_URL], capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run([str(installer), "/S"], capture_output=True)
            installer.unlink(missing_ok=True)
            exe = find_tesseract()
    if exe is None:
        warn("Tesseract is not installed - values on the scan images will not be read.")
        warn("Install it from https://github.com/UB-Mannheim/tesseract/wiki and run setup.bat again.")
        return
    set_config_values({"TESSERACT_CMD": str(exe)})
    ok(f"Tesseract: {exe}")


def setup_word():
    step("Microsoft Word (makes the PDFs for printing)")
    r = run_powershell("if (Test-Path 'Registry::HKEY_CLASSES_ROOT\\Word.Application') { 'yes' }")
    if "yes" not in r.stdout:
        warn("Microsoft Word is not installed. Reports are still made as Word files, but")
        warn("'PDF / Print' in the dashboard will not work until Word is installed.")
        return
    # Word started by a background task (as SYSTEM) fails to open documents
    # unless these Desktop folders exist
    for folder in (r"C:\Windows\System32\config\systemprofile\Desktop",
                   r"C:\Windows\SysWOW64\config\systemprofile\Desktop"):
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    ok("Word found - PDFs will be made with Word")


# ---------------------------------------------------------------------------
# 7. Scheduled tasks
# ---------------------------------------------------------------------------

def register_tasks():
    step("Auto-start tasks (run at boot, restart on failure)")
    for name, bat in TASKS.items():
        script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + {ps_quote(bat)} + '"') -WorkingDirectory {ps_quote(ROOT)}
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT1M'
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName {ps_quote(name)} -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName {ps_quote(name)}
"""
        r = run_powershell(script)
        if r.returncode == 0:
            ok(f"'{name}' registered and started")
        else:
            warn(f"Could not register '{name}':\n{r.stderr.strip()}")


# ---------------------------------------------------------------------------
# 8. Desktop shortcuts
# ---------------------------------------------------------------------------

def create_shortcuts():
    step("Desktop shortcuts")
    script = f"""
$desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut("$desktop\\Restart Ultrasound Services.lnk")
$s.TargetPath = {ps_quote(ROOT / 'Restart Services.bat')}
$s.WorkingDirectory = {ps_quote(ROOT)}
$s.IconLocation = 'shell32.dll,238'
$s.Description = 'Restart Orthanc, report pipeline and dashboard'
$s.Save()
Set-Content -Path "$desktop\\Ultrasound Dashboard.url" -Value "[InternetShortcut]`r`nURL=http://localhost:{DASHBOARD_PORT}/"
"""
    r = run_powershell(script)
    if r.returncode == 0:
        ok("'Ultrasound Dashboard' and 'Restart Ultrasound Services' on the Desktop")
    else:
        warn(f"Could not create the Desktop shortcuts: {r.stderr.strip()}")


# ---------------------------------------------------------------------------
# 9. Dashboard check + first login
# ---------------------------------------------------------------------------

def wait_for_dashboard(timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(f"http://127.0.0.1:{DASHBOARD_PORT}/", timeout=3)
            return True
        except requests.RequestException:
            time.sleep(2)
    return False


def local_ips():
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    return [ip for ip in ips if not ip.startswith("127.")]


def is_tailscale(ip):
    a, b = (int(x) for x in ip.split(".")[:2])
    return a == 100 and 64 <= b <= 127


def finish(cfg):
    step("Checking the dashboard")
    if wait_for_dashboard():
        ok(f"Dashboard is running on port {DASHBOARD_PORT}")
    else:
        warn(f"Dashboard did not answer on port {DASHBOARD_PORT} - see {ROOT / 'logs' / 'dashboard.log'}")

    print("\n============================================================")
    print("  Setup complete")
    print("============================================================")
    print(f"\n  Dashboard on this PC:  http://localhost:{DASHBOARD_PORT}")
    for ip in local_ips():
        kind = "Tailscale" if is_tailscale(ip) else "clinic LAN"
        print(f"  From the {kind}:{' ' * (12 - len(kind))}http://{ip}:{DASHBOARD_PORT}")

    if SETUP_TOKEN_FILE.exists() and getattr(cfg, "DASHBOARD_LOGIN_REQUIRED", True):
        token = SETUP_TOKEN_FILE.read_text(encoding="utf-8").strip()
        print("\n  FIRST LOGIN - open the dashboard and enter this setup token:")
        print(f"\n      {token}\n")
        print("  then create the admin account (keep it for yourself) and a staff account.")

    print("\n  Still to do by hand:")
    print("   - Dashboard > Settings: enter the reporting doctor's name and qualification.")
    print("     Until then every Word report has a blank PCPNDT declaration line.")
    lan = [ip for ip in local_ips() if not is_tailscale(ip)]
    if urlparse(cfg.ORTHANC_URL).hostname in ("localhost", "127.0.0.1"):
        print(f"   - Ultrasound machine DICOM destination: IP {lan[0] if lan else '<this PC LAN IP>'}, "
              f"port 4242, AE title as set in Orthanc.")
    print("   - Reboot once and confirm the dashboard comes back by itself.")
    print(f"\n  Logs: {ROOT / 'logs'}")


def main():
    cfg = configure()
    setup_firewall(cfg)
    setup_power()
    setup_tesseract()
    setup_word()
    register_tasks()
    create_shortcuts()
    finish(cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)

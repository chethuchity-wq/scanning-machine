"""
Dashboard Web App
===================
Minimal worklist + settings UI for the ultrasound reporting pipeline.
Runs alongside pipeline.py's watch-mode service as a separate process;
reads the same SQLite DB and reports/ folder that pipeline.py writes to.

Run: uvicorn webapp.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import config
import docx_pdf
import measurement_rules
from webapp import db, docx_editor
from webapp.auth import hash_password, verify_password

BASE_DIR = Path(__file__).resolve().parent

db.init_db()

# Session secret: persisted so logins survive process restarts, generated once on first run.
SECRET_FILE = Path(getattr(config, "SESSION_SECRET_FILE", "data/session_secret.txt"))
SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
if not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_hex(32))
SESSION_SECRET = SECRET_FILE.read_text().strip()

LOGIN_REQUIRED = getattr(config, "DASHBOARD_LOGIN_REQUIRED", True)
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

app = FastAPI(title="Ultrasound Reporting Dashboard")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


@app.middleware("http")
async def _local_only_without_login(request: Request, call_next):
    """
    With logins off, the PC itself is the only access control, so refuse
    everyone else - even if the server was started with --host 0.0.0.0.
    """
    if not LOGIN_REQUIRED:
        host = request.client.host if request.client else ""
        if host not in _LOOPBACK_HOSTS:
            return PlainTextResponse(
                "This dashboard can only be opened on the clinic PC itself.",
                status_code=403,
            )
    return await call_next(request)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class RedirectRequired(Exception):
    def __init__(self, location: str):
        self.location = location


@app.exception_handler(RedirectRequired)
async def _handle_redirect(request: Request, exc: RedirectRequired):
    return RedirectResponse(exc.location, status_code=303)


def current_user(request: Request) -> Optional[dict]:
    """
    Resolve the session against the database on every request, rather than
    trusting the cookie's contents. This keeps `role` authoritative (a
    demotion takes effect immediately) and means a deleted account's
    still-valid session cookie stops working at once, instead of lingering
    until the cookie expires.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    record = db.get_user_by_id(user_id)
    if record is None:
        request.session.clear()
        return None
    return {
        "id": record["id"],
        "username": record["username"],
        "clinic_id": record["clinic_id"],
        "role": record["role"],
    }


def require_login(request: Request) -> dict:
    if not LOGIN_REQUIRED:
        # Single local user; "local" hides the account/logout links
        return {"id": None, "username": "", "clinic_id": db.get_default_clinic_id(), "role": "local"}
    user = current_user(request)
    if user is None:
        raise RedirectRequired("/login")
    return user


def require_admin(request: Request) -> dict:
    """
    Guard for account management. Without this, `role` was stored but never
    read, so any staff account could create further accounts or delete the
    admin - the dashboard had one privilege level in practice.
    """
    accounts_enabled()
    user = require_login(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin account can manage dashboard users.",
        )
    return user


def accounts_enabled() -> None:
    """Login, setup and account pages don't exist with logins off - go to the worklist."""
    if not LOGIN_REQUIRED:
        raise RedirectRequired("/")


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------
# Every state-changing form carries a per-session token, checked on submit.
# Without this, a malicious page could submit these forms cross-site using
# the logged-in user's cookies (e.g. silently changing clinic settings or
# creating an account) - the session cookie alone doesn't stop that.

def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf_token"] = token
    return token


def check_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=400, detail="Invalid or expired form submission. Please try again.")


# ---------------------------------------------------------------------------
# First-run setup (creates the first admin account)
# ---------------------------------------------------------------------------
# Guarded by a setup token, not just "no account exists yet": without this,
# whoever reaches /setup first over the network - not necessarily the person
# who deployed the machine - could claim the admin account. The token is
# generated once at startup and printed to the console/log, so only someone
# with access to the machine (console or remote desktop, not just network
# reachability to the port) can complete setup.

SETUP_TOKEN_FILE = Path("data/setup_token.txt")


def _current_setup_token() -> Optional[str]:
    if db.user_count() > 0:
        if SETUP_TOKEN_FILE.exists():
            SETUP_TOKEN_FILE.unlink()
        return None
    if not SETUP_TOKEN_FILE.exists():
        SETUP_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETUP_TOKEN_FILE.write_text(secrets.token_urlsafe(12))
    return SETUP_TOKEN_FILE.read_text().strip()


_token = _current_setup_token() if LOGIN_REQUIRED else None
if _token:
    print("=" * 60)
    print("  First-run setup required.")
    print(f"  Setup token: {_token}")
    print("  Enter this token on the /setup page to create the admin account.")
    print("=" * 60)


@app.get("/setup", response_class=HTMLResponse, dependencies=[Depends(accounts_enabled)])
def setup_form(request: Request):
    if db.user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "setup.html", {"error": None, "csrf_token": csrf_token(request)}
    )


@app.post("/setup", dependencies=[Depends(accounts_enabled)])
def setup_submit(
    request: Request,
    setup_token: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    csrf_token_field: str = Form(..., alias="csrf_token"),
):
    check_csrf(request, csrf_token_field)
    if db.user_count() > 0:
        return RedirectResponse("/login", status_code=303)

    expected_token = _current_setup_token()
    if not expected_token or not secrets.compare_digest(expected_token, setup_token):
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": "Incorrect setup token.", "csrf_token": csrf_token(request)},
            status_code=403,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": "Password must be at least 8 characters.", "csrf_token": csrf_token(request)},
            status_code=400,
        )

    clinic_id = db.get_default_clinic_id()
    user_id = db.create_user(clinic_id, username, hash_password(password), role="admin")
    if user_id is None:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": "That username is already taken.", "csrf_token": csrf_token(request)},
            status_code=400,
        )
    if SETUP_TOKEN_FILE.exists():
        SETUP_TOKEN_FILE.unlink()

    request.session["user_id"] = user_id
    request.session["username"] = username
    request.session["clinic_id"] = clinic_id
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse, dependencies=[Depends(accounts_enabled)])
def login_form(request: Request):
    if db.user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": None, "csrf_token": csrf_token(request)}
    )


@app.post("/login", dependencies=[Depends(accounts_enabled)])
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token_field: str = Form(..., alias="csrf_token"),
):
    check_csrf(request, csrf_token_field)

    user = db.get_user_by_username(username)
    if user is None or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password", "csrf_token": csrf_token(request)},
            status_code=401,
        )

    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["clinic_id"] = user["clinic_id"]
    return RedirectResponse("/", status_code=303)


@app.get("/logout", dependencies=[Depends(accounts_enabled)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------------
# Worklist
# ---------------------------------------------------------------------------

SCAN_TYPE_NAMES = {
    "early_pregnancy": "Early pregnancy",
    "nt_scan": "NT scan",
    "anomaly_scan": "Anomaly scan",
    "growth_scan": "Growth scan",
    "follicular_study": "Follicular study",
    "abdomen_pelvis_female": "Abdomen & pelvis (F)",
    "abdomen_pelvis_male": "Abdomen & pelvis (M)",
}
STATUS_NAMES = {
    "draft": "Awaiting doctor",
    "reviewed": "Reviewed",
    "measurements": "Measurements only",
    "flagged": "Needs checking",
}


def _local_time(utc: datetime) -> str:
    """generated_at is stored in UTC; show the clinic PC's local time."""
    return utc.replace(tzinfo=timezone.utc).astimezone().strftime("%H:%M")


def _parse_day(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _decorate(entries: list[dict]) -> list[dict]:
    for e in entries:
        e["scan_name"] = SCAN_TYPE_NAMES.get(e["scan_type"], "Not identified")
        e["time"] = _local_time(e["generated_at"])
        d = _parse_day(e["study_date"])
        e["date_label"] = d.strftime("%d/%m/%Y") if d else e["study_date"]
    return entries


def _calendar(clinic_id: int, open_day: Optional[date]) -> list[dict]:
    """
    Year > month > day tree for the sidebar. Days are listed only for the
    open year - an older year shows its months, each linking to that month's
    latest day - so the sidebar stays small however many years accumulate.
    """
    years: dict = {}
    for iso, count in db.study_day_counts(clinic_id):
        d = _parse_day(iso)
        if d is None:
            continue
        year = years.setdefault(d.year, {"year": d.year, "total": 0, "months": {}})
        month = year["months"].setdefault(d.month, {
            "key": f"{d.year}-{d.month:02d}", "label": d.strftime("%B"),
            "total": 0, "days": [], "latest": iso,
        })
        year["total"] += count
        month["total"] += count
        month["days"].append({"iso": iso, "label": d.strftime("%d %a"), "count": count})
    open_year = open_day.year if open_day else (max(years) if years else None)
    open_month = f"{open_day.year}-{open_day.month:02d}" if open_day else None
    tree = []
    for y in sorted(years, reverse=True):
        year = years[y]
        months = [year["months"][m] for m in sorted(year["months"], reverse=True)]
        for m in months:
            m["open"] = m["key"] == open_month
        tree.append({**year, "months": months, "open": y == open_year})
    return tree


def _page(request: Request, user: dict, template: str, open_day: Optional[date], **context):
    """Render a page with the sidebar: calendar, and the open day's patients."""
    day_patients = _decorate(db.list_day_studies(user["clinic_id"], open_day.isoformat())) if open_day else []
    return templates.TemplateResponse(request, template, {
        "user": user,
        "calendar": _calendar(user["clinic_id"], open_day),
        "open_day": open_day,
        "day_patients": day_patients,
        "today": date.today(),
        "scan_types": SCAN_TYPE_NAMES,
        "status_names": STATUS_NAMES,
        **context,
    })


@app.get("/", response_class=HTMLResponse)
def worklist(request: Request, day: Optional[str] = None, user: dict = Depends(require_login)):
    """One study date per page, today by default."""
    shown = _parse_day(day) or date.today()
    key = shown.isoformat()
    studies = _decorate(db.list_day_studies(user["clinic_id"], key))
    days = [d for d, _ in db.study_day_counts(user["clinic_id"])]
    earlier = [d for d in days if d < key]
    later = [d for d in days if d > key]
    return _page(
        request, user, "worklist.html", shown,
        day=shown,
        is_today=shown == date.today(),
        studies=studies,
        prev_day=earlier[0] if earlier else None,
        next_day=later[-1] if later else None,
        latest_day=days[0] if days else None,
        signature=db.day_signature(user["clinic_id"], key),
        counts={
            "draft": sum(s["document_status"] == "draft" for s in studies),
            "reviewed": sum(s["document_status"] == "reviewed" for s in studies),
            "flagged": sum(bool(s["needs_review"]) for s in studies),
        },
    )


@app.get("/day-status")
def day_status(day: str, user: dict = Depends(require_login)):
    """Polled by the day page every few seconds: reload when this changes."""
    shown = _parse_day(day)
    if shown is None:
        raise HTTPException(status_code=400, detail="Bad date")
    return {"signature": db.day_signature(user["clinic_id"], shown.isoformat())}


def _study_or_404(user: dict, study_id: int) -> dict:
    study = db.get_study(user["clinic_id"], study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _decorate([study])[0]


@app.get("/study/{study_id}", response_class=HTMLResponse)
def study_page(
    request: Request,
    study_id: int,
    remade: str = "",
    error: str = "",
    user: dict = Depends(require_login),
):
    """A scan's details on top, its Word report below, editable in place."""
    study = _study_or_404(user, study_id)
    day = _parse_day(study["study_date"])
    document = None
    if study["report_type"] == "docx" and Path(study["file_path"]).exists():
        document = docx_editor.render(study["file_path"])
    scan = _scan_data(study)
    siblings = db.list_day_studies(user["clinic_id"], study["study_date"])
    ids = [s["study_id"] for s in siblings]
    i = ids.index(study_id) if study_id in ids else -1
    return _page(
        request, user, "study.html", day,
        study=study,
        document=document,
        scan=scan,
        # Guesses only when the scanner sent no labelled values to fill from
        suggestions=measurement_rules.suggest(scan["images"], study["scan_type"])
        if scan and document and not scan.get("report_values") else [],
        prev_study=ids[i - 1] if i > 0 else None,
        next_study=ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        day_total=len(ids),
        csrf_token=csrf_token(request),
        remade=bool(remade),
        error={
            "no-orthanc": "This scan was not loaded from Orthanc, so its report can't be remade here.",
            "remake": "Could not remake the report - Orthanc may be unreachable. Details are in the dashboard log.",
        }.get(error, ""),
    )


def _scan_data_dir(study: dict) -> Optional[Path]:
    """Images and values saved by the pipeline (pipeline.scan_data_dir)."""
    orthanc_id = re.sub(r"[^A-Za-z0-9-]", "", study.get("orthanc_study_id") or "")
    return Path(config.OUTPUT_DIR) / "scan_data" / orthanc_id if orthanc_id else None


def _scan_data(study: dict) -> Optional[dict]:
    folder = _scan_data_dir(study)
    try:
        return json.loads((folder / "scan.json").read_text()) if folder else None
    except (OSError, ValueError):
        return None


@app.get("/study/{study_id}/scan/{name}")
def study_scan_image(study_id: int, name: str, user: dict = Depends(require_login)):
    if not re.fullmatch(r"image_\d{2,3}\.jpg", name):
        raise HTTPException(status_code=404, detail="Not found")
    folder = _scan_data_dir(_study_or_404(user, study_id))
    if folder is None or not (folder / name).exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(folder / name, media_type="image/jpeg")


@app.get("/study/{study_id}/document")
def study_document(study_id: int, user: dict = Depends(require_login)):
    """The editor's content, re-read after a save (paragraph numbering may shift)."""
    study = _study_or_404(user, study_id)
    if study["report_type"] != "docx":
        raise HTTPException(status_code=404, detail="This scan has no Word report")
    return {**docx_editor.render(study["file_path"]), "status": study["document_status"]}


@app.post("/study/{study_id}/document")
async def save_study_document(request: Request, study_id: int, user: dict = Depends(require_login)):
    check_csrf(request, request.headers.get("X-CSRF-Token", ""))
    study = _study_or_404(user, study_id)
    if study["report_type"] != "docx":
        raise HTTPException(status_code=404, detail="This scan has no Word report")
    payload = await request.json()
    try:
        version = docx_editor.save(study["file_path"], str(payload.get("version", "")), payload.get("blocks") or [])
    except docx_editor.VersionConflict:
        raise HTTPException(
            status_code=409,
            detail="The report was changed elsewhere (e.g. in Word) since you opened it. "
                   "Reload the page to see it; your unsaved changes here will be lost.",
        )
    except PermissionError:
        raise HTTPException(status_code=423, detail="The report is open in Word. Close it in Word, then save again.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"version": version, "saved_at": datetime.now().strftime("%H:%M")}


@app.post("/study/{study_id}/report-type")
def change_report_type(
    request: Request,
    study_id: int,
    user: dict = Depends(require_login),
    scan_type: str = Form(...),
    csrf_token_field: str = Form(..., alias="csrf_token"),
):
    """
    Remake the scan's report as another form - for when the scanner's exam
    type was wrong (e.g. left on OB for an abdomen scan). Re-reads the scan
    from Orthanc. The previous report's file stays in the folder; the page
    then shows the new one.
    """
    check_csrf(request, csrf_token_field)
    study = _study_or_404(user, study_id)
    if scan_type not in SCAN_TYPE_NAMES:
        raise HTTPException(status_code=400, detail="Unknown report type")
    if not study["orthanc_study_id"]:
        return RedirectResponse(f"/study/{study_id}?error=no-orthanc", status_code=303)
    # Imported here: pulls in the DICOM/OCR stack, which only this action needs
    import pipeline
    from orthanc_client import OrthancClient
    try:
        pipeline.process_orthanc_study(OrthancClient(), study["orthanc_study_id"], scan_type=scan_type)
    except Exception as e:
        print(f"[dashboard] Remaking report as {scan_type} failed: {e}")
        return RedirectResponse(f"/study/{study_id}?error=remake", status_code=303)
    return RedirectResponse(f"/study/{study_id}?remade=1", status_code=303)


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    scan: str = "",
    status: str = "",
    user: dict = Depends(require_login),
):
    searched = any((q.strip(), date_from, date_to, scan, status))
    results, truncated = [], False
    if searched:
        results, truncated = db.search_studies(
            user["clinic_id"],
            query_text=q.strip(),
            date_from=date_from if _parse_day(date_from) else "",
            date_to=date_to if _parse_day(date_to) else "",
            scan_type=scan if scan in SCAN_TYPE_NAMES else "",
            status=status if status in STATUS_NAMES else "",
        )
    return _page(
        request, user, "search.html", None,
        q=q, date_from=date_from, date_to=date_to, scan=scan, status=status,
        searched=searched, results=_decorate(results), truncated=truncated,
    )


def _report_file(user: dict, report_id: int) -> Path:
    file_path = db.get_report_file_path(user["clinic_id"], report_id)
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return Path(file_path)


@app.get("/reports/{report_id}/download")
def download_report(report_id: int, user: dict = Depends(require_login)):
    path = _report_file(user, report_id)
    return FileResponse(path, filename=path.name)


@app.get("/reports/{report_id}/pdf")
def report_pdf(report_id: int, user: dict = Depends(require_login)):
    """
    PDF of a report, opened in the browser for printing. A Word report is
    converted by Word on request - and again whenever it has been edited
    since - so the PDF always matches the Word file.
    """
    path = _report_file(user, report_id)
    if path.suffix.lower() == ".docx":
        if docx_pdf.is_stale(path) and docx_pdf.convert(path) is None:
            raise HTTPException(
                status_code=503,
                detail="Could not create the PDF. Download the Word report and "
                       "print or save it as PDF from Word.",
            )
        path = docx_pdf.pdf_path_for(path)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request, user: dict = Depends(require_login)):
    clinic = db.get_clinic_info(user["clinic_id"])
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "clinic": clinic,
            "orthanc_url": getattr(config, "ORTHANC_URL", ""),
            "saved": False,
            "csrf_token": csrf_token(request),
        },
    )


@app.post("/settings")
def settings_submit(
    request: Request,
    user: dict = Depends(require_login),
    name: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    doctor_name: str = Form(""),
    doctor_qual: str = Form(""),
    referring_default: str = Form(""),
    csrf_token_field: str = Form(..., alias="csrf_token"),
):
    check_csrf(request, csrf_token_field)
    db.update_clinic_info(
        user["clinic_id"],
        name=name.strip(),
        address=address.strip(),
        phone=phone.strip(),
        doctor_name=doctor_name.strip(),
        doctor_qual=doctor_qual.strip(),
        referring_default=referring_default.strip(),
    )
    clinic = db.get_clinic_info(user["clinic_id"])
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "clinic": clinic,
            "orthanc_url": getattr(config, "ORTHANC_URL", ""),
            "saved": True,
            "csrf_token": csrf_token(request),
        },
    )


# ---------------------------------------------------------------------------
# User management (add/remove dashboard logins)
# ---------------------------------------------------------------------------

@app.get("/users", response_class=HTMLResponse)
def users_form(request: Request, user: dict = Depends(require_admin)):
    users = db.list_users(user["clinic_id"])
    return templates.TemplateResponse(
        request,
        "users.html",
        {"user": user, "users": users, "error": None, "added": False, "csrf_token": csrf_token(request)},
    )


@app.post("/users")
def users_create(
    request: Request,
    user: dict = Depends(require_admin),
    username: str = Form(...),
    password: str = Form(...),
    csrf_token_field: str = Form(..., alias="csrf_token"),
):
    check_csrf(request, csrf_token_field)
    users = db.list_users(user["clinic_id"])
    error = None
    added = False
    if len(password) < 8:
        error = "Password must be at least 8 characters."
    else:
        new_id = db.create_user(user["clinic_id"], username, hash_password(password), role="staff")
        if new_id is None:
            error = "That username is already taken."
        else:
            added = True
            users = db.list_users(user["clinic_id"])
    return templates.TemplateResponse(
        request,
        "users.html",
        {"user": user, "users": users, "error": error, "added": added, "csrf_token": csrf_token(request)},
    )


@app.post("/users/{user_id}/delete")
def users_delete(
    request: Request,
    user_id: int,
    user: dict = Depends(require_admin),
    csrf_token_field: str = Form(..., alias="csrf_token"),
):
    check_csrf(request, csrf_token_field)
    if user_id == user["id"]:
        # Deleting your own account mid-session leaves you logged in as a
        # user that no longer exists, and can strand the clinic with no admin.
        ok, error = False, "You can't remove the account you're signed in as."
    else:
        ok = db.delete_user(user_id, user["clinic_id"])
        error = None if ok else "Can't remove the last remaining account."
    users = db.list_users(user["clinic_id"])
    return templates.TemplateResponse(
        request,
        "users.html",
        {"user": user, "users": users, "error": error, "added": False, "csrf_token": csrf_token(request)},
    )


# ---------------------------------------------------------------------------
# Account (change own password)
# ---------------------------------------------------------------------------

@app.get("/account", response_class=HTMLResponse, dependencies=[Depends(accounts_enabled)])
def account_form(request: Request, user: dict = Depends(require_login)):
    return templates.TemplateResponse(
        request, "account.html", {"user": user, "error": None, "saved": False, "csrf_token": csrf_token(request)}
    )


@app.post("/account", dependencies=[Depends(accounts_enabled)])
def account_submit(
    request: Request,
    user: dict = Depends(require_login),
    current_password: str = Form(...),
    new_password: str = Form(...),
    csrf_token_field: str = Form(..., alias="csrf_token"),
):
    check_csrf(request, csrf_token_field)
    record = db.get_user_by_username(user["username"])
    error = None
    saved = False
    if record is None or not verify_password(current_password, record["password_hash"]):
        error = "Current password is incorrect."
    elif len(new_password) < 8:
        error = "New password must be at least 8 characters."
    else:
        db.update_password(user["id"], hash_password(new_password))
        saved = True
    return templates.TemplateResponse(
        request, "account.html", {"user": user, "error": error, "saved": saved, "csrf_token": csrf_token(request)}
    )

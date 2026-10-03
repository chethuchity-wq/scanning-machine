"""
Dashboard Web App
===================
Minimal worklist + settings UI for the ultrasound reporting pipeline.
Runs alongside pipeline.py's watch-mode service as a separate process;
reads the same SQLite DB and reports/ folder that pipeline.py writes to.

Run: uvicorn webapp.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import config
import docx_pdf
from webapp import db
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

@app.get("/", response_class=HTMLResponse)
def worklist(request: Request, user: dict = Depends(require_login)):
    reports = db.list_recent_reports(user["clinic_id"])
    return templates.TemplateResponse(
        request, "worklist.html", {"user": user, "reports": reports}
    )


@app.get("/reports/{report_id}/download")
def download_report(report_id: int, user: dict = Depends(require_login)):
    file_path = db.get_report_file_path(user["clinic_id"], report_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Report not found")
    # A PDF made from a Word report is re-made whenever the doctor has edited
    # the Word file since, so the PDF never prints something different.
    docx = Path(file_path).with_suffix(".docx")
    if file_path.lower().endswith(".pdf") and docx.exists() and docx_pdf.is_stale(docx):
        if docx_pdf.convert(docx) is None:
            raise HTTPException(
                status_code=503,
                detail="Could not create the PDF from the Word report. "
                       "Open the Word report and print or save it as PDF from Word.",
            )
    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(file_path, filename=Path(file_path).name)


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

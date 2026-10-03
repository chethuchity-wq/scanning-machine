"""
Dashboard Database
====================
SQLite-backed data layer for the web dashboard. Every row is scoped to a
clinic_id from the start, even though a single deployment currently serves
one clinic - this avoids a schema migration later if a second clinic is
ever added. pipeline.py writes to this DB after generating each report;
webapp/main.py reads from it to render the worklist and settings pages.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

import config

DB_PATH = Path(getattr(config, "DB_PATH", "data/app.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    logo_path: Mapped[str] = mapped_column(String(500), default="")
    # Reporting doctor, printed in the PCPNDT declaration on Word reports.
    doctor_name: Mapped[str] = mapped_column(String(200), default="")
    doctor_qual: Mapped[str] = mapped_column(String(200), default="")
    referring_default: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"))
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(50), default="admin")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"))
    orthanc_study_id: Mapped[str] = mapped_column(String(200), default="")
    patient_name: Mapped[str] = mapped_column(String(200), default="")
    patient_id: Mapped[str] = mapped_column(String(100), default="")
    study_date: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    reports: Mapped[list["Report"]] = relationship(back_populates="study")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"))
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"))
    report_type: Mapped[str] = mapped_column(String(20))  # "pdf" or "docx"
    scan_type: Mapped[str] = mapped_column(String(50), default="")
    file_path: Mapped[str] = mapped_column(String(1000))
    generated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    # Data-quality signal computed at generation time (unknown scan type, zero
    # measurements, zero images, etc.) - see pipeline.py's _compute_review_flags.
    # Lets a report that "succeeded" but produced questionable output stand out
    # in the worklist, instead of looking identical to a good one.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str] = mapped_column(String(500), default="")

    study: Mapped["Study"] = relationship(back_populates="reports")


def _migrate_add_review_columns() -> None:
    """
    One-off migration for deployments whose reports table predates the
    needs_review/review_reason columns. Base.metadata.create_all() only
    creates missing TABLES, not missing columns on existing ones.
    """
    inspector = inspect(engine)
    if "reports" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("reports")}
    with engine.begin() as conn:
        if "needs_review" not in existing:
            conn.execute(text("ALTER TABLE reports ADD COLUMN needs_review BOOLEAN DEFAULT 0"))
        if "review_reason" not in existing:
            conn.execute(text("ALTER TABLE reports ADD COLUMN review_reason VARCHAR(500) DEFAULT ''"))


def _migrate_add_doctor_columns() -> None:
    """
    One-off migration for clinics tables that predate the doctor columns.
    Backfills from config (blank unless config_local.py sets them), so an
    upgraded site prints a blank declaration line - and gets flagged for
    review - until someone enters the doctor on the Settings page.
    """
    inspector = inspect(engine)
    if "clinics" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("clinics")}
    with engine.begin() as conn:
        for column, config_key in (
            ("doctor_name", "DOCTOR_NAME"),
            ("doctor_qual", "DOCTOR_QUAL"),
            ("referring_default", "REFERRING_DEFAULT"),
        ):
            if column not in existing:
                conn.execute(text(f"ALTER TABLE clinics ADD COLUMN {column} VARCHAR(200) DEFAULT ''"))
                conn.execute(
                    text(f"UPDATE clinics SET {column} = :value"),
                    {"value": getattr(config, config_key, "") or ""},
                )


def init_db() -> None:
    """Create tables if needed and seed a default clinic row. Safe to call repeatedly."""
    Base.metadata.create_all(engine)
    _migrate_add_review_columns()
    _migrate_add_doctor_columns()
    with SessionLocal() as session:
        if session.query(Clinic).count() == 0:
            session.add(
                Clinic(
                    name=getattr(config, "CLINIC_NAME", ""),
                    address=getattr(config, "CLINIC_ADDRESS", ""),
                    phone=getattr(config, "CLINIC_PHONE", ""),
                    logo_path=getattr(config, "CLINIC_LOGO", "") or "",
                    doctor_name=getattr(config, "DOCTOR_NAME", "") or "",
                    doctor_qual=getattr(config, "DOCTOR_QUAL", "") or "",
                    referring_default=getattr(config, "REFERRING_DEFAULT", "") or "",
                )
            )
            session.commit()


def get_default_clinic_id() -> int:
    with SessionLocal() as session:
        clinic = session.query(Clinic).order_by(Clinic.id).first()
        return clinic.id if clinic else 1


def get_clinic_info(clinic_id: int) -> dict:
    with SessionLocal() as session:
        clinic = session.get(Clinic, clinic_id)
        if clinic is None:
            return {}
        return {
            "name": clinic.name,
            "address": clinic.address,
            "phone": clinic.phone,
            "logo_path": clinic.logo_path,
            "doctor_name": clinic.doctor_name,
            "doctor_qual": clinic.doctor_qual,
            "referring_default": clinic.referring_default,
        }


def update_clinic_info(clinic_id: int, **fields) -> None:
    with SessionLocal() as session:
        clinic = session.get(Clinic, clinic_id)
        if clinic is None:
            return
        for key, value in fields.items():
            if hasattr(clinic, key):
                setattr(clinic, key, value)
        session.commit()


def record_report(
    clinic_id: int,
    patient_name: str,
    patient_id: str,
    study_date: str,
    report_type: str,
    file_path: str,
    scan_type: str = "",
    orthanc_study_id: str = "",
    needs_review: bool = False,
    review_reason: str = "",
) -> None:
    """Record a generated report (and its parent study, if new) in the dashboard DB."""
    with SessionLocal() as session:
        study = None
        if orthanc_study_id:
            study = (
                session.query(Study)
                .filter_by(clinic_id=clinic_id, orthanc_study_id=orthanc_study_id)
                .first()
            )
        if study is None:
            study = Study(
                clinic_id=clinic_id,
                orthanc_study_id=orthanc_study_id,
                patient_name=patient_name,
                patient_id=patient_id,
                study_date=study_date,
            )
            session.add(study)
            session.flush()

        session.add(
            Report(
                clinic_id=clinic_id,
                study_id=study.id,
                report_type=report_type,
                scan_type=scan_type,
                file_path=str(file_path),
                needs_review=needs_review,
                review_reason=review_reason,
            )
        )
        session.commit()


def list_recent_reports(clinic_id: int, limit: int = 200) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(Report, Study)
            .join(Study, Report.study_id == Study.id)
            .filter(Report.clinic_id == clinic_id)
            .order_by(Report.generated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "report_id": report.id,
                "patient_name": study.patient_name,
                "patient_id": study.patient_id,
                "study_date": study.study_date,
                "report_type": report.report_type,
                "scan_type": report.scan_type,
                "file_path": report.file_path,
                "generated_at": report.generated_at,
                "needs_review": report.needs_review,
                "review_reason": report.review_reason,
                "document_status": _document_status(report.report_type, report.file_path, report.generated_at),
            }
            for report, study in rows
        ]


def _document_status(report_type: str, file_path: str, generated_at: datetime) -> str:
    """
    A PDF made from a Word report (same name, next to it) takes that Word
    report's status. Any other PDF is 'measurements' - the auto-generated
    summary made when no Word report could be, not the doctor-signed document.

    For Word docs, compares the file's last-modified time against when the
    pipeline generated it. Doctors edit the .docx in place on the clinic PC
    and save over the same file (confirmed as the actual workflow), so a
    save after generation is a reliable passive signal they've opened and
    completed it - no separate "mark as reviewed" step to forget.
    """
    if report_type != "docx":
        docx = Path(file_path).with_suffix(".docx")
        if not docx.exists():
            return "measurements"
        file_path = str(docx)
    try:
        mtime = datetime.utcfromtimestamp(Path(file_path).stat().st_mtime)
    except OSError:
        return "draft"
    return "reviewed" if mtime > generated_at + timedelta(seconds=10) else "draft"


def get_report_file_path(clinic_id: int, report_id: int) -> Optional[str]:
    with SessionLocal() as session:
        report = session.get(Report, report_id)
        if report is None or report.clinic_id != clinic_id:
            return None
        return report.file_path


def user_count() -> int:
    with SessionLocal() as session:
        return session.query(User).count()


def count_users(clinic_id: int) -> int:
    with SessionLocal() as session:
        return session.query(User).filter_by(clinic_id=clinic_id).count()


def create_user(clinic_id: int, username: str, password_hash: str, role: str = "admin") -> Optional[int]:
    """Returns the new user's id, or None if the username is already taken."""
    from sqlalchemy.exc import IntegrityError

    with SessionLocal() as session:
        user = User(clinic_id=clinic_id, username=username, password_hash=password_hash, role=role)
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        return user.id


def get_user_by_username(username: str) -> Optional[dict]:
    with SessionLocal() as session:
        user = session.query(User).filter_by(username=username).first()
        if user is None:
            return None
        return {
            "id": user.id,
            "clinic_id": user.clinic_id,
            "username": user.username,
            "password_hash": user.password_hash,
            "role": user.role,
        }


def get_user_by_id(user_id: int) -> Optional[dict]:
    """Look up a user by primary key. Returns None if the account no longer exists."""
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is None:
            return None
        return {
            "id": user.id,
            "clinic_id": user.clinic_id,
            "username": user.username,
            "password_hash": user.password_hash,
            "role": user.role,
        }


def list_users(clinic_id: int) -> list[dict]:
    with SessionLocal() as session:
        users = (
            session.query(User)
            .filter_by(clinic_id=clinic_id)
            .order_by(User.created_at)
            .all()
        )
        return [
            {"id": u.id, "username": u.username, "role": u.role, "created_at": u.created_at}
            for u in users
        ]


def delete_user(user_id: int, clinic_id: int) -> bool:
    """Deletes a user, refusing to remove the last remaining account for a clinic."""
    with SessionLocal() as session:
        if session.query(User).filter_by(clinic_id=clinic_id).count() <= 1:
            return False
        user = session.get(User, user_id)
        if user is None or user.clinic_id != clinic_id:
            return False
        session.delete(user)
        session.commit()
        return True


def update_password(user_id: int, new_password_hash: str) -> None:
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.password_hash = new_password_hash
            session.commit()

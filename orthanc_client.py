"""
Orthanc REST API Client
========================
Provides methods to interact with the Orthanc DICOM server:
- List patients, studies, series, instances
- Download DICOM files
- Monitor for new/stable studies
- Query study metadata

Usage:
    from orthanc_client import OrthancClient

    client = OrthancClient()
    studies = client.list_studies()
    client.download_study("study-orthanc-id", output_dir="./dicom_cache")
"""

import io
import time
from pathlib import Path
from typing import Optional

import pydicom
import requests
from requests.auth import HTTPBasicAuth

import config


class OrthancClient:
    """REST client for Orthanc DICOM server."""

    def __init__(
        self,
        url: str = None,
        username: str = None,
        password: str = None,
    ):
        self.url = (url or config.ORTHANC_URL).rstrip("/")
        self.auth = HTTPBasicAuth(
            username or config.ORTHANC_USERNAME,
            password or config.ORTHANC_PASSWORD,
        )
        self.session = requests.Session()
        self.session.auth = self.auth

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def test_connection(self) -> dict:
        """Test connection to Orthanc and return system info."""
        resp = self.session.get(f"{self.url}/system")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------

    def list_patients(self) -> list[str]:
        """Return list of all patient Orthanc IDs."""
        resp = self.session.get(f"{self.url}/patients")
        resp.raise_for_status()
        return resp.json()

    def get_patient(self, patient_id: str) -> dict:
        """Get patient details."""
        resp = self.session.get(f"{self.url}/patients/{patient_id}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Studies
    # ------------------------------------------------------------------

    def list_studies(self) -> list[str]:
        """Return list of all study Orthanc IDs."""
        resp = self.session.get(f"{self.url}/studies")
        resp.raise_for_status()
        return resp.json()

    def get_study(self, study_id: str) -> dict:
        """Get study details including patient info and series list."""
        resp = self.session.get(f"{self.url}/studies/{study_id}")
        resp.raise_for_status()
        return resp.json()

    def find_studies(
        self,
        patient_name: str = None,
        patient_id: str = None,
        study_date: str = None,
        modality: str = None,
    ) -> list[dict]:
        """
        Search for studies using DICOM query parameters.

        Args:
            patient_name: Patient name (supports wildcards like "Smith*")
            patient_id: Patient ID
            study_date: Study date in YYYYMMDD format (supports ranges like "20260101-20260630")
            modality: Modality filter (e.g. "US" for ultrasound)
        """
        query = {}
        if patient_name:
            query["PatientName"] = patient_name
        if patient_id:
            query["PatientID"] = patient_id
        if study_date:
            query["StudyDate"] = study_date
        if modality:
            query["ModalitiesInStudy"] = modality

        payload = {"Level": "Study", "Query": query}
        resp = self.session.post(f"{self.url}/tools/find", json=payload)
        resp.raise_for_status()

        study_ids = resp.json()
        return [self.get_study(sid) for sid in study_ids]

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------

    def list_series(self, study_id: str) -> list[str]:
        """Return list of series Orthanc IDs for a study."""
        study = self.get_study(study_id)
        return study.get("Series", [])

    def get_series(self, series_id: str) -> dict:
        """Get series details."""
        resp = self.session.get(f"{self.url}/series/{series_id}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Instances
    # ------------------------------------------------------------------

    def list_instances(self, series_id: str) -> list[str]:
        """Return list of instance Orthanc IDs for a series."""
        series = self.get_series(series_id)
        return series.get("Instances", [])

    def get_instance(self, instance_id: str) -> dict:
        """Get instance metadata."""
        resp = self.session.get(f"{self.url}/instances/{instance_id}")
        resp.raise_for_status()
        return resp.json()

    def get_instance_tags(self, instance_id: str) -> dict:
        """Get simplified DICOM tags for an instance."""
        resp = self.session.get(f"{self.url}/instances/{instance_id}/simplified-tags")
        resp.raise_for_status()
        return resp.json()

    def download_instance(self, instance_id: str) -> bytes:
        """Download raw DICOM file bytes for an instance."""
        resp = self.session.get(f"{self.url}/instances/{instance_id}/file")
        resp.raise_for_status()
        return resp.content

    def get_instance_as_dataset(self, instance_id: str) -> pydicom.Dataset:
        """Download an instance and return as pydicom Dataset (in-memory)."""
        dicom_bytes = self.download_instance(instance_id)
        return pydicom.dcmread(io.BytesIO(dicom_bytes), force=True)

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    def download_study(self, study_id: str, output_dir: str = None) -> list[Path]:
        """
        Download all DICOM instances in a study to disk.

        Args:
            study_id: Orthanc study ID
            output_dir: Directory to save files (default: config.DICOM_CACHE_DIR)

        Returns:
            List of saved file paths
        """
        output_dir = Path(output_dir or config.DICOM_CACHE_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_files = []
        series_ids = self.list_series(study_id)

        for series_id in series_ids:
            instance_ids = self.list_instances(series_id)
            for instance_id in instance_ids:
                dicom_bytes = self.download_instance(instance_id)
                file_path = output_dir / f"{instance_id}.dcm"
                file_path.write_bytes(dicom_bytes)
                saved_files.append(file_path)

        return saved_files

    def download_series(self, series_id: str, output_dir: str = None) -> list[Path]:
        """Download all instances in a series to disk."""
        output_dir = Path(output_dir or config.DICOM_CACHE_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_files = []
        instance_ids = self.list_instances(series_id)

        for instance_id in instance_ids:
            dicom_bytes = self.download_instance(instance_id)
            file_path = output_dir / f"{instance_id}.dcm"
            file_path.write_bytes(dicom_bytes)
            saved_files.append(file_path)

        return saved_files

    # ------------------------------------------------------------------
    # Change monitoring (for pipeline)
    # ------------------------------------------------------------------

    def get_changes(self, since: int = 0, limit: int = 100) -> dict:
        """
        Get recent changes from Orthanc.

        Returns dict with:
            - Changes: list of change events
            - Done: bool (no more changes)
            - Last: int (sequence number of last change)
        """
        resp = self.session.get(
            f"{self.url}/changes",
            params={"since": since, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()

    def watch_for_stable_studies(
        self,
        callback,
        poll_interval: float = None,
        since: int = 0,
    ):
        """
        Poll Orthanc for 'StableStudy' events and invoke callback for each.

        Args:
            callback: Function that receives (study_id: str, study_info: dict)
            poll_interval: Seconds between polls (default: config.POLL_INTERVAL_SECONDS)
            since: Starting change sequence number
        """
        poll_interval = poll_interval or config.POLL_INTERVAL_SECONDS
        last_seq = since

        print(f"Watching Orthanc at {self.url} for new stable studies...")
        print(f"Poll interval: {poll_interval}s | Press Ctrl+C to stop\n")

        try:
            while True:
                changes = self.get_changes(since=last_seq)

                for change in changes["Changes"]:
                    if change["ChangeType"] == "StableStudy":
                        study_id = change["ID"]
                        print(f"  [NEW] Stable study detected: {study_id}")
                        try:
                            study_info = self.get_study(study_id)
                            callback(study_id, study_info)
                        except Exception as e:
                            print(f"  [ERROR] Failed to process study {study_id}: {e}")

                last_seq = changes["Last"]

                if changes["Done"]:
                    time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\nStopped watching.")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_study_summary(self, study_id: str) -> dict:
        """
        Get a human-readable summary of a study.

        Returns:
            Dict with patient_name, patient_id, study_date, modalities,
            series_count, instance_count, description
        """
        study = self.get_study(study_id)
        main_tags = study.get("MainDicomTags", {})
        patient_tags = study.get("PatientMainDicomTags", {})

        series_ids = study.get("Series", [])
        modalities = set()
        instance_count = 0
        for sid in series_ids:
            series = self.get_series(sid)
            series_tags = series.get("MainDicomTags", {})
            modalities.add(series_tags.get("Modality", "??"))
            instance_count += len(series.get("Instances", []))

        return {
            "study_id": study_id,
            "patient_name": patient_tags.get("PatientName", "Unknown"),
            "patient_id": patient_tags.get("PatientID", ""),
            "study_date": main_tags.get("StudyDate", ""),
            "study_description": main_tags.get("StudyDescription", ""),
            "modalities": sorted(modalities),
            "series_count": len(series_ids),
            "instance_count": instance_count,
        }

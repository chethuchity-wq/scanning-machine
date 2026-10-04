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
import json
import os
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
        since: Optional[int] = None,
        state_file: str = None,
    ):
        """
        Poll Orthanc for 'StableStudy' events and invoke callback for each.

        Args:
            callback: Function that receives (study_id: str, study_info: dict)
            poll_interval: Seconds between polls (default: config.POLL_INTERVAL_SECONDS)
            since: Starting change sequence number. If None (default), resumes
                from the position saved in `state_file` so a crash/reboot of
                the watch process doesn't reprocess every historical study.
            state_file: Path to a JSON file used to persist the change-feed
                cursor across restarts (default: config.WATCH_STATE_FILE)
        """
        poll_interval = poll_interval or config.POLL_INTERVAL_SECONDS
        state_path = Path(state_file or config.WATCH_STATE_FILE)

        last_seq = since if since is not None else self._load_watch_state(state_path)

        print(f"Watching Orthanc at {self.url} for new stable studies...")
        print(f"Poll interval: {poll_interval}s | Resuming from change #{last_seq} | Press Ctrl+C to stop\n")

        try:
            while True:
                try:
                    changes = self.get_changes(since=last_seq)
                except requests.exceptions.RequestException as e:
                    # Orthanc restarting or briefly unreachable: keep the
                    # cursor and try again, instead of the whole watcher dying
                    print(f"  [WAIT] Orthanc not reachable ({e.__class__.__name__}) - retrying")
                    time.sleep(max(poll_interval, 5))
                    continue

                for change in changes["Changes"]:
                    if change["ChangeType"] == "StableStudy":
                        study_id = change["ID"]
                        print(f"  [NEW] Stable study detected: {study_id}")
                        try:
                            study_info = self.get_study(study_id)
                            callback(study_id, study_info)
                        except Exception as e:
                            print(f"  [ERROR] Failed to process study {study_id}: {e}")

                    # Advance and persist the cursor after each change (not just
                    # each poll batch) so a crash mid-batch can't cause a
                    # already-processed study to be replayed on restart.
                    last_seq = change["Seq"]
                    self._save_watch_state(state_path, last_seq)

                last_seq = changes["Last"]
                self._save_watch_state(state_path, last_seq)

                if changes["Done"]:
                    self._send_heartbeat()
                    time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\nStopped watching.")

    @staticmethod
    def _send_heartbeat() -> None:
        """
        Ping an external dead-man's-switch service (e.g. healthchecks.io) once
        per successful poll cycle, if config.HEARTBEAT_URL is set.

        Deliberately external rather than something this process alerts on
        itself: if the machine loses power, the network, or this process
        crashes outright, it can't be the one to report its own silence.
        The heartbeat service notices the pings *stop* and alerts from
        outside - which is the failure mode that actually matters for an
        unattended deployment nobody is physically next to.

        Never allowed to affect the watch loop: a failure to reach the
        heartbeat service (or none configured) is silently ignored.
        """
        heartbeat_url = getattr(config, "HEARTBEAT_URL", "") or ""
        if not heartbeat_url:
            return
        try:
            requests.get(heartbeat_url, timeout=5)
        except Exception:
            pass

    @staticmethod
    def _load_watch_state(state_path: Path) -> int:
        """
        Read the persisted change-feed cursor. Returns 0 only when no state
        file exists yet (genuine first run).

        A state file that exists but cannot be parsed FAILS CLOSED rather
        than falling back to 0. Resuming from 0 would replay Orthanc's
        entire change history, regenerating a report for every study ever
        received - which, on top of already-delivered reports, means
        re-running the pipeline over work a doctor has already completed.
        Refusing to start is recoverable; a mass reprocess is not.
        """
        if not state_path.exists():
            return 0
        try:
            last_seq = json.loads(state_path.read_text())["last_seq"]
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise RuntimeError(
                f"""Watch state file {state_path} exists but is unreadable ({e}).
Refusing to start: resuming from change #0 would reprocess every study on the
Orthanc server and overwrite existing reports.
To recover, either restore the file, or - accepting that studies received while
it was broken will be skipped - read the current change number from Orthanc
(GET /changes?last) and write it back manually, e.g.:
    {{"last_seq": 12345}}"""
            ) from e
        if not isinstance(last_seq, int) or isinstance(last_seq, bool) or last_seq < 0:
            raise RuntimeError(
                f"Watch state file {state_path} holds an invalid cursor "
                f"({last_seq!r}). Refusing to start - delete the file only if you "
                f"intend every study on the server to be reprocessed."
            )
        return last_seq

    @staticmethod
    def _save_watch_state(state_path: Path, last_seq: int) -> None:
        """
        Persist the change-feed cursor so watch mode can resume after a restart.

        Written via a temp file + atomic replace: a plain write_text truncates
        first, so losing power mid-write leaves truncated JSON, which
        _load_watch_state then (correctly) refuses to start from.

        docker-compose bind-mounts this as a single file, where os.replace
        cannot swap the inode - so that case falls back to an in-place write.
        """
        payload = json.dumps({"last_seq": last_seq})
        tmp_path = state_path.with_name(state_path.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, state_path)
        except OSError:
            # Single-file bind mount (or any filesystem that refuses the
            # rename): fall back to writing in place.
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                state_path.write_text(payload)
            except OSError as e:
                print(f"  [WARN] Could not save watch state to {state_path}: {e}")

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
            # When Orthanc last received an image of it ("20261004T101530")
            "received": study.get("LastUpdate", ""),
            "modalities": sorted(modalities),
            "series_count": len(series_ids),
            "instance_count": instance_count,
        }

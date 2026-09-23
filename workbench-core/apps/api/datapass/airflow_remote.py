"""Remote real-Airflow runner backed by ephemeral GitHub Actions jobs.

This adapter never runs Airflow on the Datapass host. It dispatches a bounded
Dag source to a dedicated workflow, polls GitHub for the run, and reads a small
result artifact. The GitHub token is server-only.

Security/truth boundaries:
- the remote job receives no repository checkout and no repository secrets;
- the workflow has empty GitHub token permissions;
- Dag source is capped because workflow_dispatch inputs have a bounded payload;
- execution is real Airflow, but ephemeral: no persistent scheduler is claimed;
- for a public execution repository, submitted Dag source/logs/artifacts should
  be treated as public educational material and must never contain credentials.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import io
import json
import os
import re
import secrets
import zipfile
from typing import Any

import httpx


DAG_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,99}$")
REQUEST_ID = re.compile(r"^[a-f0-9]{16}$")
AIRFLOW_VERSION = "3.3.2"
API_VERSION = "2026-03-10"
MAX_DAG_SOURCE_BYTES = 30_000
MAX_LOG_CHARS = 30_000


@dataclass(frozen=True)
class AirflowRemoteConfig:
    repo: str
    workflow: str
    ref: str
    token: str | None
    public_repo: bool

    @classmethod
    def from_env(cls) -> "AirflowRemoteConfig":
        return cls(
            repo=os.environ.get("DATAPASS_AIRFLOW_GITHUB_REPO", "julian-passebecq/ducklabms_code"),
            workflow=os.environ.get("DATAPASS_AIRFLOW_GITHUB_WORKFLOW", "datapass-airflow-remote.yml"),
            ref=os.environ.get("DATAPASS_AIRFLOW_GITHUB_REF", "main"),
            token=os.environ.get("DATAPASS_GITHUB_TOKEN") or None,
            public_repo=os.environ.get("DATAPASS_AIRFLOW_PUBLIC_REPO", "1") == "1",
        )

    @property
    def configured(self) -> bool:
        return bool(self.token and "/" in self.repo and self.workflow and self.ref)


class AirflowRemote:
    def __init__(self, config: AirflowRemoteConfig | None = None, *, timeout: float = 20.0):
        self.config = config or AirflowRemoteConfig.from_env()
        self.timeout = timeout

    def capabilities(self) -> dict[str, Any]:
        c = self.config
        return {
            "schema_version": 1,
            "enabled": c.configured,
            "mode": "github_actions_ephemeral",
            "airflow_version": AIRFLOW_VERSION,
            "repo": c.repo,
            "workflow": c.workflow,
            "ref": c.ref,
            "public_repo": c.public_repo,
            "truth": (
                "real remote Airflow 3 execution on an ephemeral GitHub-hosted runner"
                if c.configured
                else "unavailable until the server configures a GitHub Actions write token"
            ),
            "scheduler_truth": "ephemeral Dag test run; not a persistent Airflow scheduler",
            "privacy": (
                "Public execution repository: Dag source/logs/artifacts must contain no secrets."
                if c.public_repo
                else "Execution repository is configured private; still do not put credentials in Dag source."
            ),
            "limits": {
                "dag_source_bytes": MAX_DAG_SOURCE_BYTES,
                "job_timeout_minutes": 12,
                "dag_test_timeout_seconds": 300,
            },
        }

    def _headers(self) -> dict[str, str]:
        if not self.config.token:
            raise RuntimeError("Remote Airflow is not configured. Set DATAPASS_GITHUB_TOKEN on the FastAPI server.")
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.config.token}",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def _url(self, suffix: str) -> str:
        return f"https://api.github.com/repos/{self.config.repo}{suffix}"

    def dispatch(self, *, dag_id: str, source: str, logical_date: str) -> dict[str, Any]:
        if not self.config.configured:
            raise RuntimeError("Remote Airflow is unavailable until GitHub Actions is configured on the server.")
        if not DAG_ID.fullmatch(dag_id):
            raise ValueError("dag_id must be a simple Airflow identifier up to 100 characters.")
        raw = source.encode("utf-8")
        if not raw or len(raw) > MAX_DAG_SOURCE_BYTES:
            raise ValueError(f"Dag source must be 1..{MAX_DAG_SOURCE_BYTES} UTF-8 bytes.")
        if "\x00" in source:
            raise ValueError("Dag source may not contain NUL bytes.")
        request_id = secrets.token_hex(8)
        encoded = base64.b64encode(raw).decode("ascii")
        payload = {
            "ref": self.config.ref,
            "return_run_details": True,
            "inputs": {
                "request_id": request_id,
                "dag_id": dag_id,
                "logical_date": logical_date,
                "dag_source_b64": encoded,
            },
        }
        url = self._url(f"/actions/workflows/{self.config.workflow}/dispatches")
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.post(url, headers=self._headers(), json=payload)
        if response.status_code != 200:
            detail = response.text[:1000]
            raise RuntimeError(f"GitHub workflow dispatch failed ({response.status_code}): {detail}")
        body = response.json()
        run_id = body.get("workflow_run_id")
        if not run_id:
            raise RuntimeError("GitHub accepted the Airflow dispatch but returned no workflow run id.")
        return {
            "request_id": request_id,
            "status": "accepted",
            "run_id": int(run_id),
            "run_url": body.get("html_url"),
            "truth": "dispatch accepted by GitHub Actions; Airflow has not completed yet",
        }

    def _run(self, run_id: int) -> dict[str, Any]:
        if run_id <= 0:
            raise ValueError("Invalid GitHub Actions run id.")
        url = self._url(f"/actions/runs/{run_id}")
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(url, headers=self._headers())
        if response.status_code == 404:
            raise ValueError("Remote Airflow run not found.")
        if response.status_code != 200:
            raise RuntimeError(f"GitHub workflow status lookup failed ({response.status_code}).")
        return response.json()

    def status(self, run_id: int) -> dict[str, Any]:
        run = self._run(run_id)
        return {
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "run_id": run.get("id"),
            "run_url": run.get("html_url"),
            "created_at": run.get("created_at"),
            "run_started_at": run.get("run_started_at"),
            "updated_at": run.get("updated_at"),
            "artifact_available": run.get("status") == "completed",
            "truth": "real GitHub Actions workflow state",
        }

    def result(self, run_id: int, request_id: str) -> dict[str, Any]:
        if not REQUEST_ID.fullmatch(request_id):
            raise ValueError("Invalid Airflow request id.")
        run = self._run(run_id)
        if run.get("status") != "completed":
            raise RuntimeError("The remote Airflow run has not completed yet.")
        artifact_url = self._url(f"/actions/runs/{run_id}/artifacts")
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(artifact_url, headers=self._headers())
            if response.status_code != 200:
                raise RuntimeError(f"Could not list Airflow artifacts ({response.status_code}).")
            expected = f"datapass-airflow-{request_id}"
            artifact = next((a for a in response.json().get("artifacts", []) if a.get("name") == expected), None)
            if artifact is None:
                raise RuntimeError("The Airflow result artifact is not available.")
            archive = client.get(artifact["archive_download_url"], headers=self._headers())
            if archive.status_code != 200:
                raise RuntimeError(f"Could not download Airflow artifact ({archive.status_code}).")

        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            try:
                result = json.loads(bundle.read("result.json"))
            except (KeyError, json.JSONDecodeError) as error:
                raise RuntimeError("Airflow artifact is missing a valid result.json.") from error
            try:
                log = bundle.read("dag-test.log").decode("utf-8", "replace")
            except KeyError:
                log = ""
        result["request_id"] = request_id
        result["run_id"] = run_id
        result["run_url"] = run.get("html_url")
        result["log"] = log[-MAX_LOG_CHARS:]
        result["log_truncated"] = len(log) > MAX_LOG_CHARS
        result["truth"] = "real Airflow 3.3.2 Dag test executed on an ephemeral GitHub-hosted runner"
        return result

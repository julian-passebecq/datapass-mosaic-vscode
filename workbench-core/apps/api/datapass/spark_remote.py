"""Server-side proxy to the dedicated fastapispark service.

React never receives DATAPASS_SPARK_RUNNER_KEY. The Datapass API prepares
bounded workspace fixtures, then the remote Spark service owns GitHub Actions
dispatch/poll/artifact handling.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import httpx


@dataclass(frozen=True)
class SparkRemoteConfig:
    base_url: str | None
    runner_key: str | None

    @classmethod
    def from_env(cls) -> "SparkRemoteConfig":
        url = os.environ.get("DATAPASS_SPARK_API_URL")
        return cls(
            base_url=url.rstrip("/") if url else None,
            runner_key=os.environ.get("DATAPASS_SPARK_RUNNER_KEY") or None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.runner_key)


class SparkRemote:
    def __init__(self, config: SparkRemoteConfig | None = None, *, timeout: float = 20.0):
        self.config = config or SparkRemoteConfig.from_env()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.config.runner_key:
            raise RuntimeError("Real Spark proxy is not configured.")
        return {
            "Content-Type": "application/json",
            "X-Datapass-Runner-Key": self.config.runner_key,
        }

    def _url(self, path: str) -> str:
        if not self.config.base_url:
            raise RuntimeError("Real Spark proxy is not configured. Set DATAPASS_SPARK_API_URL.")
        return f"{self.config.base_url}{path}"

    def capabilities(self) -> dict[str, Any]:
        if not self.config.configured:
            return {
                "enabled": False,
                "mode": "github_actions_ephemeral",
                "truth": "unavailable until DATAPASS_SPARK_API_URL and DATAPASS_SPARK_RUNNER_KEY are configured on the Datapass server",
                "cluster_truth": "real Spark verification is optional; SparkLab simulation remains available",
            }
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(self._url("/v1/spark/verify/capabilities"))
        if response.status_code != 200:
            raise RuntimeError(f"Spark runner capability check failed ({response.status_code}).")
        body = response.json()
        body["proxy_truth"] = "Datapass server proxy; runner key remains server-side"
        return body

    def dispatch(self, *, code: str, tables: list[dict[str, Any]], collect_limit: int) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.post(
                self._url("/v1/spark/verify"),
                headers=self._headers(),
                json={"code": code, "tables": tables, "collect_limit": collect_limit},
            )
        if response.status_code != 202:
            detail = response.text[:1000]
            raise RuntimeError(f"Spark runner dispatch failed ({response.status_code}): {detail}")
        return response.json()

    def status(self, job_id: str | int) -> dict[str, Any]:
        path = (
            f"/v1/spark/jobs/{job_id}"
            if isinstance(job_id, str)
            else f"/v1/spark/verify/{job_id}"
        )
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(self._url(path), headers=self._headers())
        if response.status_code != 200:
            raise RuntimeError(f"Spark runner status failed ({response.status_code}): {response.text[:1000]}")
        return response.json()

    def result(self, job_id: str | int, request_id: str) -> dict[str, Any]:
        path = (
            f"/v1/spark/jobs/{job_id}/result/{request_id}"
            if isinstance(job_id, str)
            else f"/v1/spark/verify/{job_id}/result/{request_id}"
        )
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(self._url(path), headers=self._headers())
        if response.status_code != 200:
            raise RuntimeError(f"Spark runner result failed ({response.status_code}): {response.text[:1000]}")
        return response.json()

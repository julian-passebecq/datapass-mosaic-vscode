"""The Lakehouse Lab's routes (registered by datapass_runtime.main). Mission ids are validated; folders are always
`lakehouse/<id>/` inside the workspace, never a path from the request."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import lab
from .extensions import ducklake_status

router = APIRouter(prefix='/api/local/lakehouse')


class MissionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mission_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,47}$')


class RunRequest(MissionRequest):
    engine: Literal['duckdb', 'polars'] = 'duckdb'


def _workspace():
    from datapass_runtime.main import workspace_root
    return workspace_root()


def _call(function, *args):
    try:
        return function(*args)
    except lab.LabError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.post('/missions')
def missions() -> dict:
    """The shipped missions (never their checks), and whether DuckLake and trusted Python are available."""
    return lab.missions()


@router.post('/extension')
def extension() -> dict:
    """Re-read whether the ducklake extension is installed (after a Setup runtime). Never downloads."""
    return ducklake_status(refresh=True)


@router.post('/start')
def start(body: MissionRequest) -> dict:
    """(Re)build lakehouse/<id>/ from the pack; an existing folder goes to .datapass/lakehouse/attic/."""
    return _call(lab.build, _workspace(), body.mission_id)


@router.post('/run')
def run(body: RunRequest) -> dict:
    """Run the mission's SQL file on DuckDB (bounded to the folder), or its Polars file as trusted local Python."""
    return _call(lab.run, _workspace(), body.mission_id, body.engine)


@router.post('/check')
def check(body: MissionRequest) -> dict:
    """The hidden checker: files measured on disk, read-only DuckDB probes, DuckLake snapshots."""
    return _call(lab.check, _workspace(), body.mission_id)


@router.post('/storage')
def storage(body: MissionRequest) -> dict:
    """What the mission folder holds: data files and bytes per folder (measured), DuckLake snapshots (queried)."""
    return _call(lab.storage, _workspace(), body.mission_id)

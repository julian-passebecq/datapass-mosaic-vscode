"""The API Lab's runtime routes. main.py includes them with its kernel call and workspace root, so this package
never imports the FastAPI app. Every route sits behind the runtime's own auth (auth.py): the launch token and a
loopback Host. The simulated API server itself is a separate process on its own port (server.py)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .check import evaluate, sql_queries
from .model import Mission, find_mission, pack_dir
from .service import service

MissionId = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,47}$')


class MissionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mission_id: str = MissionId


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mission_id: str = MissionId
    batch_id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')


class StateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mission_id: str | None = Field(default=None, pattern=r'^[a-z0-9][a-z0-9-]{0,47}$')


def _mission(mission_id: str) -> Mission:
    try:
        return find_mission(mission_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def copy_project(mission: Mission, folder: Path) -> list[str]:
    """The mission's starting files (ingest.py, API.md), copied once: the learner's own files are never overwritten."""
    source = pack_dir() / mission.id / 'project'
    written = []
    for path in sorted(source.rglob('*')):
        if path.is_file():
            target = folder / path.relative_to(source)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                written.append(target.relative_to(folder).as_posix())
    return written


def make_router(kernel: Callable[[dict], object], root: Callable[[], Path]) -> APIRouter:
    router = APIRouter(prefix='/api/local/apilab')

    @router.post('/start')
    def start(body: MissionRequest) -> dict:
        """Start (over): the mission's files, its bronze tables dropped, a fresh simulated API (new key, day 1)."""
        mission = _mission(body.mission_id)
        workspace = root()
        folder = workspace / mission.folder
        folder.mkdir(parents=True, exist_ok=True)
        written = copy_project(mission, folder)
        kernel({'op': 'mission_setup', 'statements': [f'DROP TABLE IF EXISTS bronze.{t}' for t in mission.api.tables]})
        return {'folder': mission.folder, 'written': written, 'api': service.start(workspace, mission)}

    @router.post('/advance')
    def advance(body: AdvanceRequest) -> dict:
        """The next day of the simulated API (new and updated records, a schema change)."""
        mission = _mission(body.mission_id)
        try:
            return service.advance(root(), mission, body.batch_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post('/run')
    def run(body: MissionRequest) -> dict:
        """Run missions/<id>/ingest.py as trusted local Python in the kernel worker, against the simulated API."""
        mission = _mission(body.mission_id)
        workspace = root()
        source = workspace / mission.folder / 'ingest.py'
        if not source.is_file():
            raise HTTPException(status_code=404, detail=f'{mission.folder}/ingest.py does not exist: start the mission.')
        code = source.read_text(encoding='utf-8')
        try:
            current = service.begin_run(workspace, mission)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        try:
            result = kernel({'op': 'apilab_run', 'mission_id': mission.id, 'code': code,
                             'api_base_url': current['base_url'], 'api_key': current['key']})
        except ValueError as error:
            # Trusted Python off, or the DuckDB catalog missing: nothing ran.
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:  # a timeout or a crashed worker is this run's failure
            result = {'status': 'error', 'error': str(error), 'stdout': '', 'tables': []}
        entry = service.record_run(workspace, mission.id, current, result)
        return {**entry, 'api': service.status(workspace, mission.id)}

    @router.post('/check')
    def check(body: MissionRequest) -> dict:
        mission = _mission(body.mission_id)
        workspace = root()
        queries = sql_queries(mission)
        results = kernel({'op': 'mission_sql', 'queries': queries}) if queries else []
        return evaluate(mission, dict(zip(queries, results)), service.log(workspace, mission.id),
                        service.runs(workspace, mission.id))

    @router.post('/state')
    def state(body: StateRequest) -> dict:
        return service.status(root(), body.mission_id)

    @router.post('/stop')
    def stop() -> dict:
        service.stop()
        return {'running': False}

    return router

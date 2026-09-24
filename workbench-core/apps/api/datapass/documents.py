"""Versioned workspace documents; browser storage is not the source of truth."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import uuid
from .content import get_case
from .atomic import replace_file

ID = re.compile(r'^[a-f0-9]{32}$')


class RevisionConflict(ValueError):
    pass


class Documents:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def folder(self, id: str) -> Path:
        if not ID.fullmatch(id):
            raise ValueError('Invalid workspace ID.')
        return self.root / id

    def get(self, id: str):
        with self.lock:
            return json.loads((self.folder(id) / 'workspace.json').read_text())

    def all(self):
        rows = []
        with self.lock:
            for file in self.root.glob('*/workspace.json'):
                doc = json.loads(file.read_text())
                rows.append({k: doc[k] for k in ('id', 'title', 'case_id', 'revision', 'updated_at')})
        return sorted(rows, key=lambda d: d['updated_at'], reverse=True)

    def _write(self, doc):
        path = self.folder(doc['id']) / 'workspace.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(doc, indent=2))
        replace_file(temp, path)
        return doc

    def create(self, case_id: str | None, title: str | None = None):
        case = get_case(case_id) if case_id else None
        workspace_title = title.strip() if title is not None else (case['title'] if case else 'Interview Practice')
        if not workspace_title or len(workspace_title)>120:
            raise ValueError('Workspace title must contain 1-120 characters.')
        doc = {'schema_version': 1, 'id': uuid.uuid4().hex, 'case_id': case_id,
               'title': workspace_title, 'revision': 0, 'updated_at': datetime.now(timezone.utc).isoformat(),
               'notebook': None, 'evidence': {}, 'runs': []}
        with self.lock:
            return self._write(doc)

    def save_notebook(self, id: str, revision: int, notebook: dict):
        if len(json.dumps(notebook)) > 2_000_000:
            raise ValueError('Notebook exceeds the 2 MB document limit.')
        with self.lock:
            doc = self.get(id)
            if doc['revision'] != revision:
                raise RevisionConflict('The workspace changed. Reload before saving; your edits were not overwritten.')
            doc['notebook'] = notebook
            # Durable documents live in the shared workspace, independently of
            # which editor/view is currently mounted.
            notebook_id = notebook.get('id')
            if notebook_id is not None and (not isinstance(notebook_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', notebook_id)):
                raise ValueError('Invalid notebook ID.')
            notebooks = doc.setdefault('notebooks', {})
            if notebook_id is not None and notebook_id not in notebooks and len(notebooks) >= 100:
                raise ValueError('Workspace document limit reached; existing drafts were retained.')
            if notebook_id is not None:
                notebooks[notebook_id] = notebook
            exercise = notebook.get('exercise')
            if isinstance(exercise, dict) and isinstance(exercise.get('id'), str):
                from .exercises import definition
                try:
                    spec = definition(exercise['id'])
                except KeyError:
                    spec = None  # Disabled/uninstalled packs must not prevent saving a draft.
                if spec:
                    scope = spec['language']+'/'+spec['canonical_placement']['topic']
                    doc.setdefault('practice_resume', {})[scope] = spec['id']
            doc['revision'] += 1
            doc['updated_at'] = datetime.now(timezone.utc).isoformat()
            return self._write(doc)

    def save_workbench(self, id: str, revision: int, workbench):
        """Additive workspace state, under the same lock/CAS as notebooks and runs."""
        from .foundation import RootWorkbench, validate_workspace_references
        validated = RootWorkbench.model_validate(workbench)
        value = validated.model_dump(mode='json')
        if len(json.dumps(value).encode('utf-8')) > 2_000_000:
            raise ValueError('Workbench exceeds the 2 MB document limit.')
        with self.lock:
            doc = self.get(id)
            if doc['revision'] != revision:
                raise RevisionConflict('The workspace changed. Your workbench draft was retained; reload or export it before reconciling.')
            validate_workspace_references(validated, doc)
            self.validate_runtime_references(id, value)
            doc['workbench'] = value
            doc['revision'] += 1
            doc['updated_at'] = datetime.now(timezone.utc).isoformat()
            return self._write(doc)

    def validate_runtime_references(self, workspace_id: str, workbench: dict):
        """A browser import cannot promote user-supplied rows to local evidence."""
        def run(job_id: str, resource_id: str, kind: str):
            if not isinstance(job_id,str) or not ID.fullmatch(job_id):
                raise ValueError('Invalid local evidence identity.')
            path = self.folder(workspace_id)/'jobs'/f'{job_id}.json'
            if not path.is_file() or path.is_symlink():
                raise ValueError('Local evidence is unavailable in this workspace. Import rows as imported evidence instead.')
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('workspace_id') != workspace_id or record.get('resource_id') != resource_id or record.get('kind') != kind or record.get('truth') != 'real_local':
                raise ValueError('Local evidence does not belong to this resource/workspace.')
            return record
        for resource in workbench['resources']:
            if resource['kind']=='chart-board':
                snapshot=resource['board']['snapshot']
                if snapshot['origin']=='real_local':
                    record=run(snapshot.get('run_id'),resource['id'],'query')
                    authenticated=record.get('result',{}).get('snapshot')
                    # Optional fields may have been normalized to null by Pydantic.
                    clean=lambda x:{k:v for k,v in x.items() if v is not None} if isinstance(x,dict) else x
                    if record.get('status')!='success' or clean(authenticated)!=clean(snapshot):
                        raise ValueError('Local chart rows/provenance differ from the authenticated query result.')
            if resource['kind']=='dbt-project' and resource.get('last_run_id'):
                run(resource['last_run_id'],resource['id'],'dbt')

    def record_attempt(self, id: str, attempt: dict):
        with self.lock:
            doc = self.get(id)
            # Attempts are separate durable records, not the bounded run cache.
            path = self.folder(id)/'attempts'/f"{attempt['id']}.json"
            path.parent.mkdir(exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(attempt))
            replace_file(temp, path)
            doc['revision'] += 1
            doc['updated_at'] = datetime.now(timezone.utc).isoformat()
            self._write(doc)
            return doc['revision']

    def attempts(self, id: str):
        self.get(id)
        with self.lock:
            paths = sorted((self.folder(id)/'attempts').glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
            return [json.loads(p.read_text()) for p in paths[:200]]

    def review(self, id: str, exercise_id: str, revision: int, metadata: dict):
        from .exercises import definition
        definition(exercise_id)
        with self.lock:
            doc = self.get(id)
            if doc['revision'] != revision:
                raise RevisionConflict('The workspace changed. Reload before updating review metadata.')
            doc.setdefault('practice_review', {})[exercise_id] = metadata
            doc['revision'] += 1
            doc['updated_at'] = datetime.now(timezone.utc).isoformat()
            return self._write(doc)

    def practice_progress(self, id: str):
        """Full durable attempt aggregation, independent of the 200-row history page."""
        from .exercises import definitions
        with self.lock:
            workspace = self.get(id)
            specs = definitions()
            progress = {s['id']:dict(exercise_id=s['id'],version=s['version'],attempt_count=0,
                        solved=False,latest_result=None,last_attempted=None,best_status=None,
                        review=workspace.get('practice_review',{}).get(s['id'],{}).get('review',False)) for s in specs}
            rank = {'error':0,'failed':1,'passed':2}
            for path in (self.folder(id)/'attempts').glob('*.json'):
                attempt = json.loads(path.read_text())
                item = progress.get(attempt['exercise_id'])
                if item is None or item['version'] != attempt['exercise_version']: continue
                item['attempt_count'] += 1
                item['solved'] |= attempt['status']=='passed'
                if item['last_attempted'] is None or attempt['created_at'] > item['last_attempted']:
                    item['last_attempted'],item['latest_result'] = attempt['created_at'],attempt['status']
                if rank[attempt['status']] > rank.get(item['best_status'],-1): item['best_status']=attempt['status']
            def grouped(key):
                groups = {}
                for spec in specs:
                    for name in spec[key] if isinstance(spec[key],list) else [spec[key]]:
                        group = groups.setdefault(name,dict(total=0,solved=0))
                        group['total']+=1;group['solved']+=int(progress[spec['id']]['solved'])
                return groups
            return dict(exercises=progress,topics=grouped('topics'),difficulty=grouped('difficulty'))

    def record(self, id: str, event: dict, step_id: str | None):
        with self.lock:
            doc = self.get(id)
            # Bounded persisted history. Output previews are already bounded by the kernel.
            doc['runs'] = (doc['runs'] + [event])[-50:]
            if step_id:
                doc['evidence'][step_id] = event
            doc['revision'] += 1
            doc['updated_at'] = datetime.now(timezone.utc).isoformat()
            self._write(doc)
            return doc['revision']

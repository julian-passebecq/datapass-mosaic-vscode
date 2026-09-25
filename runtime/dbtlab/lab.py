"""The BI Lab's dbt tab: parse a project, run a dbt command with the emulation, and trace the column lineage of
its models from their compiled SQL."""
from __future__ import annotations

from typing import Any

from bilab.lab import catalog_schema
from bilab.lineage import Lineage

from .engine import DbtRunError, Runner
from .project import DbtProjectError, Project, load_project
from .render import RenderError

COMMANDS = ('build', 'run', 'test', 'seed', 'snapshot', 'compile', 'parse')
TRUTH = ('Datapass dbt emulation: Jinja rendered in a sandbox, SQL run for real on DuckDB, dbt Core and '
         'dbt-duckdb semantics for a documented subset (checked against dbt Core); not dbt Core')


def graph(project: Project) -> dict[str, Any]:
    nodes = [{'unique_id': n.unique_id, 'name': n.name, 'resource_type': n.resource_type,
              'materialized': n.materialized, 'relation': str(n.relation) if n.relation else None,
              'path': n.path, 'depends_on': n.depends_on, 'sources': [f'{s}.{t}' for s, t in n.sources],
              'tags': list(n.config.get('tags') or []), 'description': n.description, 'problem': n.problem,
              'columns': n.columns}
             for n in project.nodes.values()]
    sources = [{'name': f'{s.source}.{s.name}', 'relation': f'{s.schema}.{s.identifier}', 'description': s.description}
               for s in project.sources.values()]
    return {'nodes': nodes, 'sources': sources}


def lineage_of(catalog, project: Project, runner: Runner) -> dict[str, Any]:
    """Column lineage of every model and snapshot, from its compiled SQL (ephemeral models flow through as CTEs)."""
    lineage = Lineage({name: [c['name'] for c in columns] for name, columns in catalog_schema(catalog).items()})
    order = runner._order(set(project.nodes), 'run')
    for node in order:
        if node.resource_type not in ('model', 'snapshot') or node.materialized == 'ephemeral':
            continue
        try:
            sql = runner.compiled.get(node.unique_id) or runner.compile(node)
        except (RenderError, DbtRunError, DbtProjectError) as error:
            lineage.issues.append({'path': node.path, 'line': 1, 'message': str(error)})
            continue
        kind = 'VIEW' if node.materialized == 'view' else 'TABLE'
        lineage.add_statement(node.path, 1, f'CREATE OR REPLACE {kind} {node.relation} AS (\n{sql}\n)')
    view = lineage.view()
    view['impact'] = {f"{c['table']}.{c['column']}": lineage.impact((c['table'], c['column'])) for c in view['columns']}
    for table in view['tables']:
        if table['kind'] == 'source':
            for column in table['columns']:
                view['impact'][f"{table['name']}.{column}"] = lineage.impact((table['name'], column))
    return view


def dbt_view(catalog, files: dict[str, str], command: str, select: list[str] | None, exclude: list[str] | None,
             full_refresh: bool, variables: dict[str, Any] | None, now: str | None = None) -> dict[str, Any]:
    if command not in COMMANDS:
        raise ValueError(f'dbt {command} is not available (use {", ".join(COMMANDS)}).')
    try:
        project = load_project(files, 'silver', variables)
    except DbtProjectError as error:
        return {'status': 'invalid', 'error': str(error), 'truth': TRUTH}
    runner = Runner(catalog, project, now)
    run = None
    if command != 'parse':
        try:
            run = runner.run(command, select or None, exclude or None, full_refresh)
        except DbtRunError as error:
            return {'status': 'invalid', 'error': str(error), 'project': {'name': project.name, 'issues': project.issues},
                    **graph(project), 'truth': TRUTH}
    return {'status': run['status'] if run else 'parsed', 'project': {'name': project.name, 'issues': project.issues},
            **graph(project), 'run': run, 'lineage': lineage_of(catalog, project, runner), 'truth': TRUTH}

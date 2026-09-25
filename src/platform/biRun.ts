import type {
  BiCheckView,
  BiImpactView,
  BiLabView,
  BiLineageColumnView,
  BiLineageTableView,
  BiLineageView,
  BiModelTableView,
  BiModelView,
  BiRelationshipView,
  BiRunMode,
  BiStatementView,
  BiTableView,
  GraphEdgeView,
  GraphNodeView,
  GraphSide,
  GraphView
} from "../webview/contracts";

type Raw = Record<string, unknown>;
type Cell = string | number | boolean | null;

/** The BI Lab lives in bi/: warehouse scripts in bi/warehouse (run in name order) and the star model file. */
export const BI_FOLDER = "bi";
export const BI_SCRIPTS_FOLDER = "bi/warehouse";
export const BI_MODEL_FILE = "bi/model.json";
/** The runtime accepts 40 scripts of up to 60,000 characters and a model file of up to 100 KB. */
export const BI_LIMITS = { scripts: 40, scriptChars: 60_000, modelChars: 100_000 };

/** Warehouse scripts run in file-name order, so 00_sources.sql comes before 05_fct_sales.sql. */
export function orderScripts<T extends { name: string }>(scripts: readonly T[]): T[] {
  return [...scripts].sort((a, b) => a.name.localeCompare(b.name, "en"));
}

/** A path the webview asked to open, accepted only inside bi/ (no traversal, no drive letters). */
export function isBiPath(relative: string): boolean {
  const parts = relative.replaceAll("\\", "/").split("/").filter(Boolean);
  return parts[0] === BI_FOLDER && parts.length > 1 && !parts.some(part => part === "." || part === ".." || part.includes(":"));
}

/** Runtime `/api/local/bi/lab` response -> webview view. Truth labels are kept verbatim. */
export function toBiLabView(
  raw: unknown,
  context: { mode: BiRunMode; source: string; modelError?: string; warnings?: string[] }
): BiLabView {
  const view = asRecord(raw);
  const model = asRecord(view.model);
  const stopped = asRecord(view.stopped);
  return {
    mode: context.mode,
    source: context.source,
    status: view.status === "ok" ? "ok" : "error",
    ran: view.ran === true,
    stopped: view.stopped ? { path: str(stopped.path, ""), line: num(stopped.line, 1), message: str(stopped.message, "") } : undefined,
    statements: list(view.statements).map(toStatement),
    tables: list(view.tables).map(toTable),
    lineage: toLineage(view.lineage),
    model: view.model && !model.error ? toModel(model) : undefined,
    modelError: context.modelError ?? (typeof model.error === "string" ? model.error : undefined),
    truth: Object.fromEntries(Object.entries(asRecord(view.truth)).filter(([, v]) => typeof v === "string")) as Record<string, string>,
    warnings: context.warnings ?? []
  };
}

function toStatement(value: unknown): BiStatementView {
  const statement = asRecord(value);
  const rows = list(statement.rows).map(row => Object.fromEntries(Object.entries(asRecord(row)).map(([k, v]) => [k, cell(v)])));
  return {
    path: str(statement.path, ""),
    index: num(statement.index),
    line: num(statement.line, 1),
    kind: str(statement.kind, "STATEMENT"),
    target: optionalString(statement.target),
    status: statement.status === "error" ? "error" : "success",
    message: str(statement.message, ""),
    affected: typeof statement.affected === "number" ? statement.affected : undefined,
    columns: strings(statement.columns),
    rows
  };
}

function toTable(value: unknown): BiTableView {
  const table = asRecord(value);
  return {
    name: str(table.name, ""),
    layer: str(table.layer, ""),
    rows: typeof table.rows === "number" ? table.rows : undefined,
    columns: list(table.columns).map(column => {
      const c = asRecord(column);
      return { name: str(c.name, ""), type: str(c.type, "") };
    })
  };
}

function toLineage(value: unknown): BiLineageView {
  const lineage = asRecord(value);
  const impact: Record<string, BiImpactView[]> = {};
  for (const [key, items] of Object.entries(asRecord(lineage.impact))) {
    impact[key] = list(items).map(item => {
      const i = asRecord(item);
      return { table: str(i.table, ""), column: str(i.column, ""), effect: i.effect === "rows" ? "rows" : "value" };
    });
  }
  return {
    tables: list(lineage.tables).map((item): BiLineageTableView => {
      const t = asRecord(item);
      return {
        name: str(t.name, ""),
        kind: t.kind === "source" || t.kind === "view" ? t.kind : "table",
        columns: strings(t.columns),
        inputs: strings(t.inputs),
        statements: list(t.statements).map(s => {
          const statement = asRecord(s);
          return { path: str(statement.path, ""), line: num(statement.line, 1), kind: str(statement.kind, "") };
        })
      };
    }),
    columns: list(lineage.columns).map((item): BiLineageColumnView => {
      const c = asRecord(item);
      return {
        table: str(c.table, ""), column: str(c.column, ""), transform: str(c.transform, "expression"),
        expression: typeof c.expression === "string" ? c.expression : "", sources: strings(c.sources), origins: strings(c.origins)
      };
    }),
    influence: list(lineage.influence).map(item => {
      const i = asRecord(item);
      return { table: str(i.table, ""), source: str(i.source, ""), role: str(i.role, ""), origins: strings(i.origins) };
    }),
    impact,
    issues: list(lineage.issues).map(item => {
      const i = asRecord(item);
      return { path: str(i.path, ""), line: num(i.line, 1), message: str(i.message, "") };
    }),
    truth: str(lineage.truth, "Static analysis of the SQL text.")
  };
}

function toModel(model: Raw): BiModelView {
  // The runtime profiles each relationship on the data: observed cardinality, orphans, NULL keys.
  const profiles = new Map(list(model.profiles).map(item => {
    const p = asRecord(item);
    return [str(p.relationship, ""), p] as const;
  }));
  return {
    name: str(model.name, "model"),
    description: typeof model.description === "string" ? model.description : "",
    tables: list(model.tables).map((item): BiModelTableView => {
      const t = asRecord(item);
      const scd = asRecord(t.scd);
      return {
        name: str(t.name, ""),
        role: t.role === "fact" || t.role === "bridge" ? t.role : "dimension",
        key: optionalString(t.key),
        businessKey: strings(t.business_key),
        grain: strings(t.grain),
        unknownMember: optionalString(t.unknown_member),
        scdType: typeof scd.type === "number" ? scd.type : undefined,
        description: typeof t.description === "string" ? t.description : ""
      };
    }),
    relationships: list(model.relationships).map((item): BiRelationshipView => {
      const r = asRecord(item);
      const profile = profiles.get(`${str(r.from, "")} -> ${str(r.to, "")}`);
      return {
        from: str(r.from, ""),
        to: str(r.to, ""),
        cardinality: str(r.cardinality, "many-to-one"),
        crossFilter: r.cross_filter === "both" ? "both" : "single",
        active: r.active !== false,
        observed: profile ? str(profile.observed, "") || undefined : undefined,
        fromRows: profile && typeof profile.from_rows === "number" ? profile.from_rows : undefined,
        orphans: profile && typeof profile.orphans === "number" ? profile.orphans : undefined,
        nullKeys: profile && typeof profile.null_keys === "number" ? profile.null_keys : undefined
      };
    }),
    checks: list(model.checks).map((item): BiCheckView => {
      const c = asRecord(item);
      return {
        check: str(c.check, ""), subject: str(c.subject, ""),
        status: c.status === "fail" || c.status === "warn" ? c.status : "pass", detail: typeof c.detail === "string" ? c.detail : ""
      };
    })
  };
}

const CARDINALITY_LABEL: Record<string, string> = {
  "many-to-one": "*:1", "one-to-one": "1:1", "one-to-many": "1:*", "many-to-many": "*:*"
};

/** Worst status of the checks about a table (or its relationships), for coloring the star's nodes. */
export function tableStatus(table: string, checks: readonly BiCheckView[]): "success" | "failed" | "warning" | undefined {
  const mine = checks.filter(c => c.subject === table || c.subject.split(" -> ").some(side => side.startsWith(`${table}.`)));
  if (!mine.length) return undefined;
  if (mine.some(c => c.status === "fail")) return "failed";
  if (mine.some(c => c.status === "warn")) return "warning";
  return "success";
}

/** The star: facts in the middle, dimensions on an ellipse around them, bridges below. Edges carry *:1 labels and
 * leave each fact by the side that faces their dimension. */
export function starGraph(model: BiModelView): GraphView {
  const facts = model.tables.filter(t => t.role === "fact");
  const bridges = model.tables.filter(t => t.role === "bridge");
  const dimensions = model.tables.filter(t => t.role === "dimension");
  const positions = new Map<string, { x: number; y: number }>();
  // Several facts sit on a diagonal, so an edge from one fact to a dimension does not cross another fact.
  facts.forEach((t, i) => {
    const offset = i - (facts.length - 1) / 2;
    positions.set(t.name, { x: Math.round(offset * 250), y: Math.round(offset * 130) });
  });
  bridges.forEach((t, i) => positions.set(t.name, { x: 300 + i * 260, y: 260 }));
  dimensions.forEach((t, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(dimensions.length, 1);
    positions.set(t.name, { x: Math.round(520 * Math.cos(angle)), y: Math.round((facts.length > 1 ? 340 : 260) * Math.sin(angle)) });
  });
  const nodes: GraphNodeView[] = model.tables.map(t => ({
    id: t.name,
    label: t.name,
    detail: t.role === "dimension"
      ? [`key ${t.key ?? "?"}`, t.scdType !== undefined ? `SCD type ${t.scdType}` : "", t.unknownMember !== undefined ? `unknown ${t.unknownMember}` : ""]
          .filter(Boolean).join(" · ")
      : `grain ${t.grain.join(", ") || "not declared"}`,
    truth: t.role,
    status: tableStatus(t.name, model.checks),
    position: positions.get(t.name),
    allSides: true
  }));
  const edges: GraphEdgeView[] = model.relationships.map((r, index) => {
    const source = r.from.split(".").slice(0, 2).join(".");
    const target = r.to.split(".").slice(0, 2).join(".");
    const [sourceSide, targetSide] = facing(positions.get(source), positions.get(target));
    return {
      id: `rel-${index}`,
      source,
      target,
      label: `${CARDINALITY_LABEL[r.cardinality] ?? r.cardinality} ${r.from.split(".").pop()}${r.crossFilter === "both" ? " ⇄" : ""}`,
      className: [r.active ? "" : "bi-edge-inactive", r.crossFilter === "both" ? "bi-edge-both" : ""].filter(Boolean).join(" ") || undefined,
      sourceSide,
      targetSide
    };
  });
  return { nodes, edges };
}

/** The sides two nodes face each other by: horizontal when they are further apart across than down. */
export function facing(from?: { x: number; y: number }, to?: { x: number; y: number }): [GraphSide, GraphSide] {
  if (!from || !to) return ["right", "left"];
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) >= Math.abs(dy) * 1.6) return dx >= 0 ? ["right", "left"] : ["left", "right"];
  return dy >= 0 ? ["bottom", "top"] : ["top", "bottom"];
}

/** Tables and what they read, left to right: sources, then what each script builds from them. */
export function tableLineageGraph(lineage: BiLineageView, rows: ReadonlyMap<string, number | undefined>): GraphView {
  return {
    nodes: lineage.tables.map(t => ({
      id: t.name,
      label: t.name,
      detail: `${t.kind === "source" ? "not built by these scripts" : t.kind}${rows.get(t.name) !== undefined ? ` · ${rows.get(t.name)} rows` : ""}`,
      truth: t.kind === "source" ? "input" : t.kind
    })),
    edges: lineage.tables.flatMap(t => t.inputs.map(input => ({ id: `${input}->${t.name}`, source: input, target: t.name, label: "" })))
  };
}

/** One column's lineage: every column it is computed from, hop by hop back to its origins. */
export function columnLineageGraph(lineage: BiLineageView, table: string, column: string): GraphView {
  const byKey = new Map(lineage.columns.map(c => [`${c.table}.${c.column}`, c]));
  const nodes = new Map<string, GraphNodeView>();
  const edges = new Map<string, GraphEdgeView>();
  const visit = (key: string, depth: number) => {
    if (nodes.has(key) || depth > 12) return;
    const info = byKey.get(key);
    nodes.set(key, {
      id: key,
      label: key,
      detail: info ? `${info.transform}${info.expression && info.transform !== "copy" ? `: ${info.expression}` : ""}` : "source column",
      truth: info ? info.transform : "source",
      status: depth === 0 ? "running" : undefined
    });
    for (const source of info?.sources ?? []) {
      edges.set(`${source}->${key}`, { id: `${source}->${key}`, source, target: key, label: "" });
      visit(source, depth + 1);
    }
  };
  visit(`${table}.${column}`, 0);
  // Right to left by hops from the column; wide columns because qualified column names are long.
  const depth = new Map<string, number>([[`${table}.${column}`, 0]]);
  const queue = [`${table}.${column}`];
  while (queue.length) {
    const key = queue.shift()!;
    for (const edge of edges.values()) {
      if (edge.target === key && !depth.has(edge.source)) {
        depth.set(edge.source, depth.get(key)! + 1);
        queue.push(edge.source);
      }
    }
  }
  const deepest = Math.max(0, ...depth.values());
  const rows = new Map<number, number>();
  for (const node of nodes.values()) {
    const level = depth.get(node.id) ?? 0;
    const row = rows.get(level) ?? 0;
    rows.set(level, row + 1);
    node.position = { x: (deepest - level) * 420, y: row * 120 };
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

/** Row influence of a table: the columns its filters, joins and groupings use. */
export function influenceOf(lineage: BiLineageView, table: string): { source: string; role: string }[] {
  const seen = new Set<string>();
  return lineage.influence
    .filter(i => i.table === table)
    .filter(i => (seen.has(`${i.source}|${i.role}`) ? false : (seen.add(`${i.source}|${i.role}`), true)))
    .map(i => ({ source: i.source, role: i.role }));
}

export function checkCounts(checks: readonly BiCheckView[]): { pass: number; fail: number; warn: number } {
  return {
    pass: checks.filter(c => c.status === "pass").length,
    fail: checks.filter(c => c.status === "fail").length,
    warn: checks.filter(c => c.status === "warn").length
  };
}

function cell(value: unknown): Cell {
  if (value === null || value === undefined) return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
  return JSON.stringify(value);
}

function asRecord(value: unknown): Raw {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Raw : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === "string");
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function optionalString(value: unknown): string | undefined {
  if (typeof value === "number") return String(value);
  return typeof value === "string" && value ? value : undefined;
}

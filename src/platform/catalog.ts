export type CatalogAction = "read" | "clone" | "configure" | "run" | "scaffold" | "deploy";

export interface ToolCatalogItem {
  id: string;
  name: string;
  category: string;
  kind: string;
  source: string;
  url: string;
  relativePath?: string;
  actions: CatalogAction[];
}

export interface ToolCatalog {
  schemaVersion: number;
  items: ToolCatalogItem[];
}

const allowedActions = new Set<CatalogAction>(["read", "clone", "configure", "run", "scaffold", "deploy"]);

export function parseToolCatalog(raw: unknown): ToolCatalog {
  if (!raw || typeof raw !== "object") throw new Error("Tool catalog must be an object.");
  const candidate = raw as { schemaVersion?: unknown; items?: unknown };
  if (candidate.schemaVersion !== 1) throw new Error("Unsupported tool catalog schema version.");
  if (!Array.isArray(candidate.items)) throw new Error("Tool catalog items must be an array.");

  const ids = new Set<string>();
  const items = candidate.items.map((value, index) => {
    if (!value || typeof value !== "object") throw new Error(`Tool catalog item ${index} must be an object.`);
    const item = value as Record<string, unknown>;
    for (const key of ["id", "name", "category", "kind", "source", "url"]) {
      if (typeof item[key] !== "string" || !String(item[key]).trim()) {
        throw new Error(`Tool catalog item ${index} has invalid ${key}.`);
      }
    }
    if (ids.has(String(item.id))) throw new Error(`Duplicate tool catalog id: ${item.id}`);
    ids.add(String(item.id));
    if (!Array.isArray(item.actions) || item.actions.some(action => !allowedActions.has(action as CatalogAction))) {
      throw new Error(`Tool catalog item ${item.id} has invalid actions.`);
    }
    return {
      id: String(item.id),
      name: String(item.name),
      category: String(item.category),
      kind: String(item.kind),
      source: String(item.source),
      url: String(item.url),
      relativePath: typeof item.relativePath === "string" ? item.relativePath : undefined,
      actions: item.actions as CatalogAction[]
    } satisfies ToolCatalogItem;
  });

  return { schemaVersion: 1, items };
}

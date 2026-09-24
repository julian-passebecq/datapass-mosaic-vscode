/**
 * Project-portable Mosaic layout stored at .datapass/mosaic.json.
 *
 * Geometry only: block ids and grid positions. Source stays in native files and
 * no runtime state, paths or secrets are serialized. Unknown blocks, unknown
 * schema versions and malformed values are dropped rather than trusted.
 */

export const MOSAIC_LAYOUT_PATH = ".datapass/mosaic.json";
export const MOSAIC_LAYOUT_SCHEMA_VERSION = 1;
export const MOSAIC_BLOCKS = ["sql", "python", "data", "notes"] as const;
export const MOSAIC_COLUMNS = 12;

export type MosaicBlockId = typeof MOSAIC_BLOCKS[number];

export interface MosaicLayoutItem {
  i: MosaicBlockId;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface MosaicLayoutDocument {
  schemaVersion: typeof MOSAIC_LAYOUT_SCHEMA_VERSION;
  layout: MosaicLayoutItem[];
}

export const MOSAIC_DEFAULT_LAYOUT: readonly MosaicLayoutItem[] = [
  { i: "sql", x: 0, y: 0, w: 6, h: 9 },
  { i: "python", x: 6, y: 0, w: 6, h: 9 },
  { i: "data", x: 0, y: 9, w: 7, h: 9 },
  { i: "notes", x: 7, y: 9, w: 5, h: 7 }
];

const MAX_ROW = 400;
const MAX_HEIGHT = 60;

/** Returns a clean layout, or undefined when nothing usable remains. */
export function sanitizeMosaicLayout(raw: unknown): MosaicLayoutItem[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const seen = new Set<string>();
  const items: MosaicLayoutItem[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Record<string, unknown>;
    const id = item.i;
    if (typeof id !== "string" || !(MOSAIC_BLOCKS as readonly string[]).includes(id) || seen.has(id)) continue;
    const w = int(item.w, 1, MOSAIC_COLUMNS);
    const h = int(item.h, 1, MAX_HEIGHT);
    const x = int(item.x, 0, MOSAIC_COLUMNS - 1);
    const y = int(item.y, 0, MAX_ROW);
    if (w === undefined || h === undefined || x === undefined || y === undefined) continue;
    seen.add(id);
    items.push({ i: id as MosaicBlockId, x: Math.min(x, MOSAIC_COLUMNS - w), y, w, h });
  }
  return items.length ? items : undefined;
}

/** Add default geometry for any block missing from a partial layout (placed below it). */
export function completeMosaicLayout(items: readonly MosaicLayoutItem[]): MosaicLayoutItem[] {
  const present = new Set(items.map(item => item.i));
  const bottom = items.reduce((max, item) => Math.max(max, item.y + item.h), 0);
  const missing = MOSAIC_DEFAULT_LAYOUT
    .filter(item => !present.has(item.i))
    .map(item => ({ ...item, y: bottom + item.y }));
  return [...items, ...missing];
}

/** Parse a stored document; anything but a known schema version is ignored. */
export function parseMosaicLayoutDocument(text: string): MosaicLayoutItem[] | undefined {
  try {
    const doc = JSON.parse(text) as Partial<MosaicLayoutDocument>;
    if (!doc || typeof doc !== "object" || doc.schemaVersion !== MOSAIC_LAYOUT_SCHEMA_VERSION) return undefined;
    const layout = sanitizeMosaicLayout(doc.layout);
    return layout && completeMosaicLayout(layout);
  } catch {
    return undefined;
  }
}

export function serializeMosaicLayout(layout: MosaicLayoutItem[]): string {
  const doc: MosaicLayoutDocument = { schemaVersion: MOSAIC_LAYOUT_SCHEMA_VERSION, layout };
  return JSON.stringify(doc, null, 2) + "\n";
}

function int(value: unknown, min: number, max: number): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
  const rounded = Math.round(value);
  return rounded < min || rounded > max ? undefined : rounded;
}

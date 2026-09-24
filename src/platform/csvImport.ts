/**
 * Mosaic "Import CSV into catalog": host-side checks before the CSV text is sent
 * to POST /api/local/import-csv. The runtime re-validates everything; these only
 * give fast, specific feedback.
 */

/** Same byte limit as runtime/datapass_runtime/local_data.parse_csv. */
export const CSV_IMPORT_MAX_BYTES = 1_000_000;

const BRONZE_ASSET = /^bronze\.[A-Za-z][A-Za-z0-9_]{0,62}$/;

/** Suggest a free bronze table name from a file name, e.g. "Retail Orders.csv" → "bronze.retail_orders". */
export function suggestBronzeAsset(fileName: string, existing: Iterable<string>): string {
  const taken = new Set(Array.from(existing, name => name.toLowerCase()));
  const stem = fileName.replace(/^.*[\\/]/, "").replace(/\.[^.]*$/, "");
  let table = stem
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!/^[a-z]/.test(table)) table = `csv_${table}`.replace(/_+$/g, "");
  table = table.slice(0, 56);

  let candidate = `bronze.${table}`;
  for (let suffix = 2; taken.has(candidate.toLowerCase()); suffix += 1) {
    candidate = `bronze.${table}_${suffix}`;
  }
  return candidate;
}

/** Return an error message for the input box, or undefined when the name is usable. */
export function validateBronzeAsset(value: string, existing: Iterable<string>): string | undefined {
  const name = value.trim();
  if (!BRONZE_ASSET.test(name)) {
    return "Use bronze.<name>: a letter first, then letters, digits or underscores (max 63).";
  }
  const lower = name.toLowerCase();
  for (const asset of existing) {
    if (asset.toLowerCase() === lower) return `${name} already exists. Imports never overwrite; choose a new name.`;
  }
  return undefined;
}

/** Decode strictly as UTF-8 so a Latin-1/UTF-16 file is refused instead of silently mangled. */
export function decodeCsvBytes(bytes: Uint8Array): string {
  if (bytes.byteLength > CSV_IMPORT_MAX_BYTES) {
    throw new Error(`The CSV is ${formatBytes(bytes.byteLength)}; the local import limit is 1 MB. Filter or split it first.`);
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error("The CSV is not valid UTF-8. Re-save it as UTF-8 and try again.");
  }
  if (!text.replace(/^﻿/, "").trim()) throw new Error("The CSV file is empty.");
  return text;
}

function formatBytes(bytes: number): string {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.ceil(bytes / 1000)} KB`;
}

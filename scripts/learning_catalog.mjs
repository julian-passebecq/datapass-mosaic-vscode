// Reads the shipped Learning catalog from disk (index + one file per path), as the extension host does.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { assembleCatalog } from '../media/learning/model.mjs';

export function loadCatalogDocument(extensionRoot) {
  const folder = path.join(extensionRoot, 'content', 'learning');
  const read = file => JSON.parse(readFileSync(file, 'utf8'));
  return assembleCatalog(read(path.join(folder, 'catalog.json')), id => read(path.join(folder, 'paths', `${id}.json`)));
}

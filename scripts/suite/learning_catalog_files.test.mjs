import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { assembleCatalog, validateCatalog } from '../../media/learning/model.mjs';
import { loadCatalogDocument } from '../learning_catalog.mjs';

const root = fileURLToPath(new URL('../..', import.meta.url));

test('every path file is listed in the index and the assembled catalog validates', () => {
  const catalog = validateCatalog(loadCatalogDocument(root));
  const files = readdirSync(path.join(root, 'content/learning/paths')).map(n => n.replace(/\.json$/, '')).sort();
  assert.deepEqual(catalog.paths.map(p => p.id).sort(), files);
});

test('a path file must name its own path and use the path format', () => {
  const index = { format: 'datapass.learning', version: 1, paths: ['a-path'] };
  const file = { format: 'datapass.learning-path', version: 1, path: { id: 'other', title: 't', summary: 's', lessons: [] }, lessons: [] };
  assert.throws(() => assembleCatalog(index, () => file), /names another path/);
  assert.throws(() => assembleCatalog(index, () => ({ ...file, format: 'x' })), /unsupported path file/);
  assert.throws(() => assembleCatalog({ ...index, paths: ['../x'] }, () => file), /invalid path id/);
  assert.throws(() => assembleCatalog({ ...index, extra: 1 }, () => file), /unknown field/);
});

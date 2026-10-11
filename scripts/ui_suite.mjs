// Runs every scripts/ui-suite/*.mjs in name order against the packaged VSIX; stops at the first failure.
import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const folder = path.join(path.dirname(fileURLToPath(import.meta.url)), 'ui-suite');
for (const name of readdirSync(folder).filter(n => n.endsWith('.mjs')).sort()) {
  console.log(`ui-suite: ${name}`);
  const result = spawnSync(process.execPath, [path.join(folder, name)], { stdio: 'inherit' });
  if (result.status !== 0) { console.error(`ui-suite: ${name} failed`); process.exit(result.status ?? 1); }
}

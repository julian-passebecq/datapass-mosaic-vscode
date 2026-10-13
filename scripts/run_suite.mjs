// Runs every scripts/suite/*.test.mjs with node --test (a directory argument is not portable across Node versions).
import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const folder = path.join(path.dirname(fileURLToPath(import.meta.url)), 'suite');
const files = readdirSync(folder).filter(n => n.endsWith('.test.mjs')).sort().map(n => path.join(folder, n));
if (!files.length) { console.error('scripts/suite: no test files'); process.exit(1); }
const result = spawnSync(process.execPath, ['--test', ...files], { stdio: 'inherit' });
process.exit(result.status ?? 1);

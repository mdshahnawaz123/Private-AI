// Rebuild the offline browser library and worker from the same pinned converter package.
import { build } from 'esbuild';
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const pkgRoot = path.join(here, 'node_modules/@thatopen/fragments');
const target = path.resolve(here, '../../ui/vendor_fragments/fragments');
const pkg = JSON.parse(await readFile(path.join(pkgRoot, 'package.json'), 'utf8'));
await mkdir(path.join(target, 'Worker'), { recursive: true });
await build({
  entryPoints: [path.join(pkgRoot, 'dist/index.mjs')],
  outfile: path.join(target, 'index.mjs'),
  bundle: true, minify: true, keepNames: true, format: 'esm', platform: 'browser',
  external: ['three', 'web-ifc'], legalComments: 'eof',
});
await build({
  entryPoints: [path.join(pkgRoot, 'dist/index.mjs')],
  outfile: path.join(target, 'index.debug.mjs'),
  bundle: true, keepNames: true, format: 'esm', platform: 'browser',
  external: ['three', 'web-ifc'], legalComments: 'eof',
});
await copyFile(path.join(pkgRoot, 'dist/Worker/worker.mjs'), path.join(target, 'Worker/worker.mjs'));
const files = {};
for (const rel of ['index.mjs', 'index.debug.mjs', 'Worker/worker.mjs']) {
  const bytes = await readFile(path.join(target, rel));
  files[rel] = { bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
}
await writeFile(path.join(target, 'version.json'), JSON.stringify({
  package: pkg.name, version: pkg.version,
  source: `https://github.com/ThatOpen/engine_fragment/releases/tag/v${pkg.version}`,
  files,
}, null, 2) + '\n');
console.log(JSON.stringify({ version: pkg.version, files }, null, 2));

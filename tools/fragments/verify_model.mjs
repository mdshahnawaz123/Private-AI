// Read a converted model back without WebGL; catch empty/broken conversions.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { SingleThreadedFragmentsModel } from '@thatopen/fragments';

if (!process.argv[2]) throw new Error('Usage: node verify_model.mjs model.frag');
const bytes = new Uint8Array(await readFile(process.argv[2]));
const model = new SingleThreadedFragmentsModel('upgrade-verification', bytes);
try {
  await model.ready;
  const geometry = model.getItemsIdsWithGeometry();
  const categories = model.getCategories();
  assert.ok(geometry.length > 0, 'Model must contain geometry');
  assert.ok(categories.length > 0, 'Model must retain IFC categories');
  const guids = model.getGuidsByLocalIds(geometry.slice(0, 10));
  assert.ok(guids.some(Boolean), 'Geometry must retain IFC GUIDs');
  console.log(JSON.stringify({ ok: true, geometryItems: geometry.length, categories,
    sampleGuids: guids, metadata: model.getMetadata() }, null, 2));
} finally {
  model.dispose();
}

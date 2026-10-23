# IFC → Fragments converter

Converts a raw `.ifc` into The Open Company **Fragments** binary (`.frag`) — ~9× smaller
and much faster to load. Runs server-side (Node) and is invoked automatically by the
backend as a background task when an `.ifc` is uploaded (see `convert_ifc_to_fragments`
in `main.py`).

## One-time install (on the machine that runs the backend)

```bash
cd tools/fragments
npm install
```

This pins `@thatopen/fragments@3.4.8`, `web-ifc@0.0.77`, `three@0.186.1`.
Fragments 3.4.8 is a compatible patch with fixes for tile updates, three r185+
transforms, highlights, disposal, grids and geometry deduplication. The existing
web-ifc and Three.js pins satisfy its peer requirements and remain unchanged.
Rebuild the offline viewer library and worker together with `npm run build:browser`.
`ui/vendor_fragments/fragments/version.json` records their version and SHA256 hashes.

Requires Node 20.11+ (`node --version`). On Windows, make sure `node` is on `PATH`.

## Manual use / testing

```bash
node convert_ifc_to_frag.mjs path/to/model.ifc path/to/model.ifc.frag
```

Prints a one-line JSON result on success, e.g.:

```json
{"ok":true,"in":"model.ifc","out":"model.ifc.frag","inBytes":83656608,"outBytes":9080832,"ratio":9.21,"ms":9850}
```

On missing dependencies or a conversion error it prints `{"ok":false,"error":"..."}` to
stderr and exits non-zero. The backend treats any failure as "skip" — the original `.ifc`
is kept and the viewer falls back to parsing it directly, so a missing/broken converter
never blocks uploads.

## Backfill existing models

To convert models that were uploaded before conversion worked (no re-upload needed):

```bash
cd tools/fragments
node backfill.mjs
```

Walks `data/docs/` and converts every `.ifc` that doesn't already have a `.frag`
sibling. Pass a directory to limit scope: `node backfill.mjs "../../data/docs/<project>"`.
Add `--force` to re-convert and overwrite existing `.frag` files (e.g. after a
converter change): `node backfill.mjs --force`.

## Backend controls (environment variables)

| Var | Default | Meaning |
|-----|---------|---------|
| `EXPO_FRAGMENTS_CONVERT` | `1` | `0` disables upload-time conversion entirely. |
| `EXPO_NODE_BIN` | `node` | Path to the Node binary if not on `PATH`. |
| `EXPO_FRAGMENTS_TIMEOUT` | `900` | Per-file conversion timeout, seconds. |

import fs from 'fs';
import * as THREE from 'three';
import { Components, FragmentsManager, IfcLoader } from '@thatopen/components';

(async () => {
    // We will patch the bytes inside memory for the local test
    const rawBytes = fs.readFileSync('../../data/docs/C3045 - Expo Valley Views/Models/C3085-MDL-3EH6117-AR-0000001.ifc');
    let patchedBytes = new Uint8Array(rawBytes);

    // Python test script printed the site coordinates
    const anchorE = 481559607.9999999;
    const anchorN = 2761729448.0;
    const anchorZ = 0.0;
    
    // We can run string replace on the buffer (IFC is ASCII)
    const rawString = new TextDecoder().decode(rawBytes);
    // `#101=IFCCARTESIANPOINT((481559607.99999988,2761729448.,0.));` -> `#101=IFCCARTESIANPOINT((0.0,0.0,0.0));     ` (pad with spaces to keep byte length same)
    let patchedString = rawString.replace(
        "IFCCARTESIANPOINT((481559607.99999988,2761729448.,0.))", 
        "IFCCARTESIANPOINT((0.0,0.0,0.0))                      "
    );
    patchedBytes = new TextEncoder().encode(patchedString);
    
    // Setup Real Coordinates (unpatched with bumped threshold)
    const componentsReal = new Components();
    const fragmentsReal = componentsReal.get(FragmentsManager);
    const ifcLoaderReal = componentsReal.get(IfcLoader);
    await ifcLoaderReal.setup();
    ifcLoaderReal.settings.wasm = { path: '', absolute: true };
    ifcLoaderReal.settings.webIfc.COORDINATE_TO_ORIGIN = false;
    // Actually the distanceThreshold is on IfcGeometryProcessor which isn't directly exposed easily or we can just patch IfcLoader internals
    try { ifcLoaderReal.settings.webIfc.distanceThreshold = 1e9; } catch (e) {}

    // Bump threshold
    try {
        ifcLoaderReal._serializer = ifcLoaderReal._serializer || {};
        ifcLoaderReal._serializer.distanceThreshold = 1e9;
    } catch(e) {}
    
    console.log("Loading unpatched model...");
    let modelReal = await ifcLoaderReal.load(rawBytes);
    console.log("Loaded unpatched model successfully.");

    // Setup Local Coordinates (patched, normal threshold)
    const componentsLocal = new Components();
    const fragmentsLocal = componentsLocal.get(FragmentsManager);
    const ifcLoaderLocal = componentsLocal.get(IfcLoader);
    await ifcLoaderLocal.setup();
    ifcLoaderLocal.settings.wasm = { path: '', absolute: true };
    ifcLoaderLocal.settings.webIfc.COORDINATE_TO_ORIGIN = false;

    console.log("Loading patched model...");
    let modelLocal = await ifcLoaderLocal.load(patchedBytes);
    console.log("Loaded patched model successfully.");

    // Select 3 known GUIDs (from the comparison file we know 2Hi7Pz7ZT9N8tns68uI_Ng)
    const testGuids = [
        "2Hi7Pz7ZT9N8tns68uI_Ng"
    ];

    async function getPos(model, guid) {
        // find item expressID
        const map = await model.getProperties(0); // wait, not easily accessible without properties
    }
    
    console.log("Test script scaffolded.");
})();

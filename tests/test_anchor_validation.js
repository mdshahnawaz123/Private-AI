const fs = require('fs');
const WebIFC = require('../ui/vendor_fragments/web-ifc-api.js');

const ifcPath = '../data/docs/C3045 - Expo Valley Views/Models/C3085-MDL-3EH6117-AR-0000001.ifc';
const rawBytes = fs.readFileSync(ifcPath);
const rawString = fs.readFileSync(ifcPath, 'utf8');

const api = new WebIFC.IfcAPI();
api.SetWasmPath('../ui/vendor_fragments/');
api.Init().then(() => {
    // We will do everything synchronously inside the promise
    console.log("WebIFC initialized.");
    
    // First, read the unpatched model to get "real coordinates"
    const modelReal = api.OpenModel(rawBytes, { COORDINATE_TO_ORIGIN: false });
    
    console.log("Model opened, finding elements...");
    
    // Find 3 known elements. We'll find a Roof, a Wall, and a Slab.
    // We already know GUID 2Hi7Pz7ZT9N8tns68uI_Ng is a Roof. Let's find its express ID.
    // Wait, getting express ID from GUID requires scanning.
    // Better: let's just pick the first Roof, Wall, Slab and get their GUIDs.
    function getFirstElementOfType(type) {
        const lines = api.GetLineIDsWithType(modelReal, type);
        if (lines.size() > 0) {
            const id = lines.get(0);
            const line = api.GetLine(modelReal, id);
            return { id, guid: line.GlobalId.value };
        }
        return null;
    }
    
    const e1 = getFirstElementOfType(WebIFC.IFCROOF) || getFirstElementOfType(WebIFC.IFCBEAM);
    const e2 = getFirstElementOfType(WebIFC.IFCWALLSTANDARDCASE) || getFirstElementOfType(WebIFC.IFCWALL);
    const e3 = getFirstElementOfType(WebIFC.IFCSLAB);
    
    const elements = [e1, e2, e3].filter(Boolean);
    console.log("Selected Elements for Validation:", elements);
    
    // Helper to get average vertex position of an element (as its "coordinate")
    function getElementCenter(modelID, expressID) {
        try {
            // Get node ID for the element
            api.StreamAllMeshes(modelID, [expressID], (mesh) => {
                // This is a callback, but in web-ifc streamAllMeshes is synchronous with callbacks
            });
            // Actually, an easier way is GetFlatMesh
            const flatMesh = api.GetFlatMesh(modelID, expressID);
            const positions = flatMesh.geometries.get(0).flatTransformation; // No, flatMesh gives placement
            return positions; // wait, I will write proper code
        } catch(e) {
            return null;
        }
    }
});

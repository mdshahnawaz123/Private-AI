pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';

let pdfDoc = null;
let pageNum = 1;
let pageRendering = false;
let pageNumPending = null;
let scale = 1;
let currentTool = 'select';
let documentId = null;
let currentFileName = "Not available";
let annotations = []; // the master list
let historyStack = [];
let redoStack = [];

const pdfCanvas = document.getElementById('pdfCanvas');
const drawCanvas = document.getElementById('drawCanvas');
const pdfCtx = pdfCanvas.getContext('2d');
const drawCtx = drawCanvas.getContext('2d');
const viewerContainer = document.getElementById('viewerContainer');

let viewport = null;
let currentPdfData = null; // base64 cache for export

document.getElementById('fileInput').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if(file.type !== 'application/pdf') { alert("Please select a valid PDF."); return; }
    currentFileName = file.name;
    documentId = file.name.replace('.pdf', '');
    document.getElementById('metaFile').innerText = currentFileName;
    document.getElementById('metaTitle').innerText = currentFileName; // mock
    document.getElementById('metaNum').innerText = documentId;
    document.getElementById('metaDate').innerText = new Date(file.lastModified).toLocaleDateString();
    
    const fileReader = new FileReader();
    fileReader.onload = function() {
        const typedarray = new Uint8Array(this.result);
        currentPdfData = this.result; // keep ArrayBuffer for base64
        
        pdfjsLib.getDocument(typedarray).promise.then(pdf => {
            pdfDoc = pdf;
            document.getElementById('pageCount').innerText = pdf.numPages;
            pageNum = 1;
            annotations = [];
            historyStack = [];
            redoStack = [];
            // load annotations from backend
            fetch("/api/annotations/" + documentId).then(r=>r.json()).then(data => {
                if(Array.isArray(data)) annotations = data;
                renderPage(pageNum);
                renderComments();
            }).catch(e => {
                renderPage(pageNum);
                renderComments();
            });
        });
    };
    fileReader.readAsArrayBuffer(file);
});

function renderPage(num) {
    pageRendering = true;
    pdfDoc.getPage(num).then(page => {
        // Calculate scale based on dropdown
        let unscaledViewport = page.getViewport({scale: 1});
        const zoomVal = document.getElementById('zoomSelect').value;
        if (zoomVal === 'page-fit') {
            const hRatio = viewerContainer.clientHeight / unscaledViewport.height;
            const wRatio = (viewerContainer.clientWidth - 40) / unscaledViewport.width;
            scale = Math.min(hRatio, wRatio) * 0.95;
        } else if (zoomVal === 'page-width') {
            scale = ((viewerContainer.clientWidth - 40) / unscaledViewport.width) * 0.95;
        } else {
            scale = parseFloat(zoomVal);
        }
        
        viewport = page.getViewport({scale: scale});
        pdfCanvas.height = viewport.height;
        pdfCanvas.width = viewport.width;
        drawCanvas.height = viewport.height;
        drawCanvas.width = viewport.width;
        
        document.getElementById('pdfContainer').style.width = viewport.width + 'px';
        document.getElementById('pdfContainer').style.height = viewport.height + 'px';

        const renderContext = { canvasContext: pdfCtx, viewport: viewport };
        const renderTask = page.render(renderContext);
        
        renderTask.promise.then(() => {
            pageRendering = false;
            redrawAnnotations();
            if (pageNumPending !== null) {
                renderPage(pageNumPending);
                pageNumPending = null;
            }
        });
    });
    document.getElementById('pageNum').innerText = num;
}

function redrawAnnotations() {
    drawCtx.clearRect(0, 0, drawCanvas.width, drawCanvas.height);
    if(!viewport) return;
    
    annotations.forEach(a => {
        if (a.page_number !== pageNum) return;
        const x = a.x * viewport.width;
        const y = a.y * viewport.height;
        const w = a.width * viewport.width;
        const h = a.height * viewport.height;
        
        drawCtx.strokeStyle = "red";
        drawCtx.fillStyle = "rgba(255,0,0,0.2)";
        drawCtx.lineWidth = 2;
        drawCtx.font = "14px Arial";
        
        if (a.annotation_type === "rectangle" || a.annotation_type === "highlight") {
            if (a.annotation_type === "highlight") {
                drawCtx.fillStyle = "rgba(255, 255, 0, 0.4)";
                drawCtx.fillRect(x, y, w, h);
            } else {
                drawCtx.strokeRect(x, y, w, h);
            }
        } else if (a.annotation_type === "text" || a.annotation_type === "comment") {
            drawCtx.fillStyle = "red";
            drawCtx.fillText(a.comment_text || "[Text]", x, y + 14);
        } else if (a.annotation_type === "circle") {
            drawCtx.beginPath();
            drawCtx.ellipse(x + w/2, y + h/2, Math.abs(w/2), Math.abs(h/2), 0, 0, 2*Math.PI);
            drawCtx.stroke();
        } else if (a.annotation_type === "line" || a.annotation_type === "arrow" || a.annotation_type === "strikeout" || a.annotation_type === "underline") {
            drawCtx.beginPath();
            drawCtx.moveTo(x, y);
            drawCtx.lineTo(x + w, y + h);
            drawCtx.stroke();
            if(a.annotation_type === "arrow") {
                // simple arrowhead
                const angle = Math.atan2(h, w);
                drawCtx.lineTo(x+w - 10*Math.cos(angle - Math.PI/6), y+h - 10*Math.sin(angle - Math.PI/6));
                drawCtx.moveTo(x+w, y+h);
                drawCtx.lineTo(x+w - 10*Math.cos(angle + Math.PI/6), y+h - 10*Math.sin(angle + Math.PI/6));
                drawCtx.stroke();
            }
        } else if (a.annotation_type === "cloud") {
            drawCtx.setLineDash([5, 5]);
            drawCtx.strokeRect(x, y, w, h);
            drawCtx.setLineDash([]);
        }
    });
}

function queueRenderPage(num) {
    if (pageRendering) { pageNumPending = num; } else { renderPage(num); }
}

document.getElementById('btnPrev').addEventListener('click', () => { if (pageNum <= 1) return; pageNum--; queueRenderPage(pageNum); renderComments(); });
document.getElementById('btnNext').addEventListener('click', () => { if (pageNum >= pdfDoc.numPages) return; pageNum++; queueRenderPage(pageNum); renderComments(); });
document.getElementById('zoomSelect').addEventListener('change', () => queueRenderPage(pageNum));
document.getElementById('btnZoomIn').addEventListener('click', () => { document.getElementById('zoomSelect').value = "1.5"; queueRenderPage(pageNum); });
document.getElementById('btnZoomOut').addEventListener('click', () => { document.getElementById('zoomSelect').value = "0.75"; queueRenderPage(pageNum); });

document.querySelectorAll('.tool-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        currentTool = e.target.getAttribute('data-tool');
        drawCanvas.style.pointerEvents = (currentTool === 'select' || currentTool === 'pan') ? 'none' : 'auto';
        viewerContainer.style.cursor = currentTool === 'pan' ? 'grab' : 'default';
    });
});

let isDrawing = false;
let startX = 0; let startY = 0;
let tempX = 0; let tempY = 0;

drawCanvas.addEventListener('mousedown', (e) => {
    if(currentTool === 'select' || currentTool === 'pan') return;
    isDrawing = true;
    const rect = drawCanvas.getBoundingClientRect();
    startX = e.clientX - rect.left;
    startY = e.clientY - rect.top;
    tempX = startX; tempY = startY;
});

drawCanvas.addEventListener('mousemove', (e) => {
    if(!isDrawing) return;
    const rect = drawCanvas.getBoundingClientRect();
    tempX = e.clientX - rect.left;
    tempY = e.clientY - rect.top;
    
    redrawAnnotations();
    drawCtx.strokeStyle = "blue";
    drawCtx.lineWidth = 1;
    drawCtx.strokeRect(startX, startY, tempX - startX, tempY - startY);
});

drawCanvas.addEventListener('mouseup', (e) => {
    if(!isDrawing) return;
    isDrawing = false;
    
    const rect = drawCanvas.getBoundingClientRect();
    const endX = e.clientX - rect.left;
    const endY = e.clientY - rect.top;
    
    // Normalize coordinates
    const nx = startX / viewport.width;
    const ny = startY / viewport.height;
    const nw = (endX - startX) / viewport.width;
    const nh = (endY - startY) / viewport.height;
    
    if (currentTool === 'eraser') {
        // Find intersection and delete
        const hit = annotations.findIndex(a => a.page_number === pageNum && a.x < nx && a.x + a.width > nx && a.y < ny && a.y + a.height > ny);
        if (hit !== -1) {
            const delId = annotations[hit].id;
            annotations.splice(hit, 1);
            if(delId) fetch("/api/annotations/" + delId, {method:"DELETE"});
            historyStack.push({type: 'delete', hit});
            redrawAnnotations();
            renderComments();
        }
        return;
    }
    
    let textVal = "";
    if (currentTool === 'text' || currentTool === 'comment') {
        textVal = prompt("Enter text/comment:");
        if(!textVal) { redrawAnnotations(); return; }
    }
    
    const ann = {
        document_id: documentId,
        drawing: documentId,
        annotation_type: currentTool,
        x: nx, y: ny, width: nw, height: nh,
        page_number: pageNum,
        comment_text: textVal || currentTool.toUpperCase() + " Annotation",
        status: "OPEN"
    };
    
    fetch("/api/annotations", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(ann)
    }).then(r=>r.json()).then(res => {
        annotations.push(res);
        historyStack.push({type: 'add', item: res});
        redoStack = [];
        redrawAnnotations();
        renderComments();
    });
});

function renderComments() {
    const list = document.getElementById('commentList');
    list.innerHTML = "";
    const filter = document.getElementById('filterStatus').value;
    
    const pageAnns = annotations.filter(a => a.page_number === pageNum);
    const filtered = filter === "ALL" ? pageAnns : pageAnns.filter(a => a.status === filter);
    
    if(filtered.length === 0) { list.innerHTML = "<div style='color:#888;text-align:center;'>No comments found.</div>"; return; }
    
    filtered.forEach(a => {
        const div = document.createElement('div');
        div.className = "comment-item";
        div.innerHTML = `
            <div class="comment-head"><span>ID: ${a.id ? a.id.substring(0,6) : 'new'}</span> <span class="comment-status status-${a.status}">${a.status}</span></div>
            <div class="comment-text"><b>${a.annotation_type.toUpperCase()}:</b> ${a.comment_text}</div>
            <div style="font-size:10px; color:#888;">By ${a.author}</div>
        `;
        list.appendChild(div);
    });
}
document.getElementById('filterStatus').addEventListener('change', renderComments);

document.getElementById('btnExportExcel').addEventListener('click', () => {
    if(!documentId) return;
    window.location.href = "/api/annotations/export/excel/" + documentId;
});

function _arrayBufferToBase64( buffer ) {
    var binary = '';
    var bytes = new Uint8Array( buffer );
    var len = bytes.byteLength;
    for (var i = 0; i < len; i++) {
        binary += String.fromCharCode( bytes[ i ] );
    }
    return window.btoa( binary );
}

document.getElementById('btnExportPdf').addEventListener('click', () => {
    if(!documentId || !currentPdfData) return;
    const b64 = _arrayBufferToBase64(currentPdfData);
    fetch("/api/annotations/export/pdf", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({document_id: documentId, file_data: "data:application/pdf;base64," + b64})
    }).then(r=>r.json()).then(res => {
        if(res.pdf_data) {
            const a = document.createElement("a");
            a.href = res.pdf_data;
            a.download = documentId + "_Annotated.pdf";
            a.click();
        }
    });
});

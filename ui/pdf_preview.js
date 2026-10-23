/* Shared, offline PDF loader. Never enable PDF-supplied JavaScript. */
(() => {
  'use strict';
  let library;
  const base = '/ui/vendor_pdfjs/';
  function load() {
    if (!library) {
      library = import(base + 'build/pdf.mjs').then(pdf => {
        pdf.GlobalWorkerOptions.workerSrc = base + 'build/pdf.worker.mjs';
        return pdf;
      }).catch(error => { library = undefined; throw error; });
    }
    return library;
  }
  window.ExpoPDF = Object.freeze({
    async open(data) {
      const pdf = await load();
      // Security options are applied last, so callers cannot override them.
      return pdf.getDocument({
        data,
        cMapUrl: base + 'cmaps/', cMapPacked: true,
        standardFontDataUrl: base + 'standard_fonts/',
        wasmUrl: base + 'wasm/',
        isEvalSupported: false, enableScripting: false,
      }).promise;
    },
  });
})();

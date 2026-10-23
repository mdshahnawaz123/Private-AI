/* Readiness is a server processing state, separate from a local PDF thumbnail. */
(() => {
  'use strict';
  window.ExpoAttachmentProcessing = Object.freeze({
    async waitReady(id, {headers = {}, onProgress = () => {}, fetcher = fetch,
                         pause = ms => new Promise(resolve => setTimeout(resolve, ms)),
                         maxPolls = 600} = {}) {
      for (let poll = 0; poll < maxPolls; poll++) {
        const response = await fetcher('/chat/attachments/' + encodeURIComponent(id), {headers, cache:'no-store'});
        const record = await response.json();
        if (!response.ok) throw new Error(record.detail || 'Attachment status unavailable');
        onProgress(record);
        if (record.status === 'ready') return record;
        if (record.status === 'error') throw new Error('Document processing failed. Re-upload the file or retry extraction.');
        await pause(poll < 20 ? 700 : 1500);
      }
      throw new Error('Document processing is taking longer than expected. Check the attachment status before retrying.');
    },
  });
})();

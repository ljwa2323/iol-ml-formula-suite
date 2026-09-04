(function () {
  let pendingList = [];
  let currentIndex = 0;
  let results = [];

  const loadStatus = document.getElementById('loadStatus');
  const fillStatus = document.getElementById('fillStatus');
  const collectStatus = document.getElementById('collectStatus');
  const exportStatus = document.getElementById('exportStatus');

  function setStatus(el, text, isError) {
    el.textContent = text;
    el.className = 'status ' + (isError ? 'error' : 'ok');
  }

  document.getElementById('fileInput').addEventListener('change', function (e) {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = function () {
      try {
        pendingList = JSON.parse(r.result);
        if (!Array.isArray(pendingList)) {
          setStatus(loadStatus, 'JSON must be an array', true);
          return;
        }
        currentIndex = 0;
        setStatus(loadStatus, 'Loaded ' + pendingList.length + ' sample(s). Index 0.', false);
      } catch (err) {
        setStatus(loadStatus, 'Parse error: ' + err.message, true);
      }
    };
    r.readAsText(f, 'UTF-8');
  });

  document.getElementById('btnFill').addEventListener('click', async function () {
    fillStatus.textContent = '';
    if (!pendingList.length) {
      setStatus(fillStatus, 'Load JSON first.', true);
      return;
    }
    if (currentIndex >= pendingList.length) {
      setStatus(fillStatus, 'All samples filled. No more.', true);
      return;
    }
    const item = pendingList[currentIndex];
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id) {
        setStatus(fillStatus, 'No active tab.', true);
        return;
      }
      if (!tab.url || !tab.url.includes('rbfcalculator.com')) {
        setStatus(fillStatus, 'Open RBF calculator page first.', true);
        return;
      }
      await chrome.tabs.sendMessage(tab.id, { action: 'fill', payload: item });
      setStatus(fillStatus, 'Filled: ' + (item.id || '') + ' ' + (item.eye || '') + ' (index ' + currentIndex + '). Click Calculate and verify, then Collect.', false);
    } catch (err) {
      setStatus(fillStatus, 'Error: ' + err.message, true);
    }
  });

  document.getElementById('btnCollect').addEventListener('click', async function () {
    collectStatus.textContent = '';
    if (currentIndex >= pendingList.length) {
      setStatus(collectStatus, 'No current sample to attach result to.', true);
      return;
    }
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id) {
        setStatus(collectStatus, 'No active tab.', true);
        return;
      }
      const result = await chrome.tabs.sendMessage(tab.id, { action: 'collect' });
      const item = pendingList[currentIndex];
      const row = {
        id: item.id,
        eye: item.eye,
        row_index: item.row_index,
        recommended_iol: result && result.recommended_iol != null ? result.recommended_iol : null,
        result_text: result && result.result_text ? result.result_text : null,
        table_text: result && result.table_text ? result.table_text : null
      };
      results.push(row);
      currentIndex += 1;
      setStatus(collectStatus, 'Collected. Total ' + results.length + '. Next index: ' + currentIndex + '.', false);
    } catch (err) {
      setStatus(collectStatus, 'Error: ' + err.message, true);
    }
  });

  document.getElementById('btnExport').addEventListener('click', function () {
    exportStatus.textContent = '';
    if (!results.length) {
      setStatus(exportStatus, 'No results to export.', true);
      return;
    }
    const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'rbf_results.json';
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus(exportStatus, 'Downloaded rbf_results.json (' + results.length + ' rows).', false);
  });
})();

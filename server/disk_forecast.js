/* Forecasts scan a week of reports; request them only when the user opens one. */
(() => {
  const cache = new Map();
  const selector = 'details[data-forecast-url]';
  async function forecasts(url) {
    const saved = cache.get(url);
    if (saved && saved.until > Date.now()) return saved.promise;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    const entry = {until: Date.now() + 60000};
    entry.promise = (async () => {
      try {
        const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw Error('Не удалось загрузить прогноз');
        const data = await response.json();
        if (!data.disks || typeof data.disks !== 'object') throw Error('Некорректный ответ прогноза');
        entry.until = Date.now() + 60000;
        return data.disks;
      } catch (error) {
        if (cache.get(url) === entry) cache.delete(url);
        throw error;
      } finally { clearTimeout(timeout); }
    })();
    cache.set(url, entry);
    if (cache.size > 32) cache.delete(cache.keys().next().value);
    return entry.promise;
  }
  async function load(node) {
    if (!node.open || !node.getClientRects().length || node.dataset.forecastState) return;
    node.dataset.forecastState = 'loading';
    const result = node.querySelector('.disk-forecast-result');
    result.textContent = 'Загрузка прогноза…';
    result.setAttribute('aria-busy', 'true');
    try {
      const disks = await forecasts(node.dataset.forecastUrl);
      if (!node.isConnected) return;
      if (Object.prototype.hasOwnProperty.call(disks, node.dataset.diskPath)) result.innerHTML = disks[node.dataset.diskPath];
      else result.textContent = 'Диск больше не представлен в текущем отчёте.';
      node.dataset.forecastState = 'loaded';
    } catch (_) {
      if (!node.isConnected) return;
      node.dataset.forecastState = 'error';
      result.textContent = 'Не удалось загрузить прогноз. ';
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.textContent = 'Повторить';
      retry.addEventListener('click', () => { delete node.dataset.forecastState; load(node); });
      result.append(retry);
    } finally { result.removeAttribute('aria-busy'); }
  }
  let scheduled = false;
  function scan() {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => { scheduled = false; document.querySelectorAll(selector).forEach(load); });
  }
  document.addEventListener('toggle', scan, true);
  const live = document.getElementById('server-live');
  if (live) new MutationObserver(scan).observe(live.closest('.server-detail') || live, {
    childList: true, subtree: true, attributes: true, attributeFilter: ['open', 'hidden', 'data-detail-tab']
  });
  scan();
})();

(() => {
  const root = document.getElementById('history-content');
  if (!root) return;

  let pending;
  const expanded = new Set();

  function restore() {
    for (const chart of root.querySelectorAll('[data-chart-key]')) {
      const open = expanded.has(chart.dataset.chartKey);
      chart.classList.toggle('is-expanded', open);
      const button = chart.querySelector('.chart-expand');
      button.textContent = open ? 'Сузить' : 'Расширить';
      button.setAttribute('aria-expanded', String(open));
    }
  }

  async function load(details, updateSelection = false) {
    pending?.abort();
    const controller = new AbortController();
    pending = controller;
    const status = details.querySelector('[data-history-status]');
    const retry = details.querySelector('[data-history-retry]');
    const panels = details.querySelector('[data-history-panels]');
    const url = new URL(location.href);
    if (updateSelection) {
      for (const select of details.querySelectorAll('.io-selector select')) {
        url.searchParams.set(select.name, select.value);
      }
    }
    const fragment = new URL(url);
    fragment.searchParams.set('details', 'fragment');
    retry.hidden = true;
    status.textContent = panels.childElementCount ? 'Обновляем дополнительные графики…' : 'Загружаем историю дисков, сети и доступности…';
    panels.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(fragment, {signal: controller.signal, credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error('History details request failed');
      const next = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (controller.signal.aborted || !details.isConnected) return;
      if (!next.querySelector('.io-selector')) throw new Error('History details are missing');
      panels.replaceChildren(...next.body.childNodes);
      if(updateSelection)window.portalMotion?.reveal(panels);
      status.textContent = '';
      if (updateSelection) {
        for (const select of details.querySelectorAll('.io-selector select')) {
          url.searchParams.set(select.name, select.value);
          const input = root.querySelector('.history-date-filter [name="'+select.name+'"]');
          if (input) input.value = select.value;
        }
        for (const link of root.querySelectorAll('.periods a')) {
          const target = new URL(link.href);
          for (const key of ['nic', 'disk', 'capacity_disk']) target.searchParams.set(key, url.searchParams.get(key) || '');
          link.href = target;
        }
        history.replaceState(null, '', url.pathname + url.search + url.hash);
      }
      restore();
    } catch (error) {
      if (controller.signal.aborted || !details.isConnected) return;
      status.textContent = 'Не удалось загрузить дополнительные графики.';
      retry.hidden = false;
      retry.onclick = () => load(details, updateSelection);
    } finally {
      if (pending === controller) {
        pending = null;
        panels.removeAttribute('aria-busy');
      }
    }
  }

  root.addEventListener('click', event => {
    const button = event.target.closest('.chart-expand');
    if (!button) return;
    const key = button.closest('[data-chart-key]').dataset.chartKey;
    if (expanded.has(key)) expanded.delete(key);
    else expanded.add(key);
    restore();
  });
  root.addEventListener('change', event => {
    if (!event.target.matches('.io-selector select')) return;
    const details = event.target.closest('[data-history-details]');
    if (details) load(details, true);
    else event.target.form.requestSubmit();
  });
  root.addEventListener('history-refresh', () => {
    const details = root.querySelector('[data-history-details]');
    if (details && !pending) load(details);
  });
  const details = root.querySelector('[data-history-details]');
  if (details) load(details);
})();

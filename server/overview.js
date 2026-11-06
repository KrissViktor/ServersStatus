(() => {
  const form = document.querySelector('.searchbar');
  if (!form || !window.fetch || !window.AbortController) return;
  const input = form.elements.q;
  const view = form.elements.view;
  const status = document.querySelector('.search-status');
  const results = document.getElementById('server-results');
  let timer, pending, version = 0;

  function updateResults(next) {
    const oldGrid = results.querySelector('.server-grid');
    const newGrid = next.querySelector('.server-grid');
    if (!oldGrid || !newGrid) {
      if (results.innerHTML !== next.innerHTML) results.replaceChildren(...next.childNodes);
      return;
    }
    // Keep unchanged cards and focused links in place during background updates.
    const existing = new Map([...oldGrid.children].map(card => [card.dataset.serverId, card]));
    const wanted = new Set();
    let cursor = oldGrid.firstElementChild;
    for (const card of [...newGrid.children]) {
      const id = card.dataset.serverId;
      wanted.add(id);
      let current = existing.get(id);
      if (!current) current = card;
      else if (current.outerHTML !== card.outerHTML && !current.contains(document.activeElement)) {
        current.replaceWith(card);
        if (cursor === current) cursor = card;
        current = card;
      }
      if (current !== cursor) oldGrid.insertBefore(current, cursor);
      cursor = current.nextElementSibling;
    }
    for (const [id, card] of existing) if (!wanted.has(id)) card.remove();
  }

  async function search(background = false) {
    clearTimeout(timer);
    if (background && (pending || document.hidden || form.contains(document.activeElement))) return;
    if (pending) pending.abort();
    const current = ++version;
    const controller = new AbortController();
    pending = controller;
    const url = new URL('/', window.location.origin);
    if (input.value) url.searchParams.set('q', input.value);
    if (view.value !== 'all') url.searchParams.set('view', view.value);
    if (!background) status.textContent = 'Обновляем список…';
    results.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(url, {
        signal: controller.signal, credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error('Search failed');
      const nextPage = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (current !== version) return;
      const next = nextPage.getElementById('server-results');
      if (!next) {
        status.textContent = 'Сессия завершена. Обновите страницу для входа.';
        return;
      }
      const x = window.scrollX, y = window.scrollY;
      // Removing filtered cards must not clamp the viewport to the page bottom.
      document.body.style.minHeight = Math.max(window.innerHeight, y + window.innerHeight) + 'px';
      updateResults(next);
      for (const id of ['overview-alerts', 'overview-stats']) {
        const target = document.getElementById(id), source = nextPage.getElementById(id);
        if (target && source && target.innerHTML !== source.innerHTML) target.innerHTML = source.innerHTML;
      }
      document.querySelector('.result-count').textContent =
        nextPage.querySelector('.result-count').textContent;
      if (!background) history.replaceState(null, '', url.pathname + url.search);
      status.textContent = '';
      window.scrollTo({left: x, top: y, behavior: 'instant'});
    } catch (error) {
      if (error.name !== 'AbortError' && current === version) {
        status.textContent = 'Не удалось обновить список. Повторите ввод или обновите страницу.';
      }
    } finally {
      if (current === version) {
        results.removeAttribute('aria-busy');
        pending = null;
      }
    }
  }

  input.addEventListener('input', () => {
    if (pending) pending.abort();
    pending = null;
    ++version;
    clearTimeout(timer);
    timer = setTimeout(() => search(false), 180);
  });
  view.addEventListener('change', () => search(false));
  form.addEventListener('submit', event => { event.preventDefault(); search(false); });
  setInterval(() => search(true), 10000);
})();

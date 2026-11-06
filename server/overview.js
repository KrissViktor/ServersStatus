(() => {
  const form = document.querySelector('.searchbar');
  if (!form || !window.fetch || !window.AbortController) return;
  const input = form.elements.q;
  const view = form.elements.view;
  const status = document.querySelector('.search-status');
  const results = document.getElementById('server-results');
  let timer, pending, version = 0;

  async function search() {
    clearTimeout(timer);
    if (pending) pending.abort();
    const current = ++version;
    pending = new AbortController();
    const url = new URL('/', window.location.origin);
    if (input.value) url.searchParams.set('q', input.value);
    if (view.value !== 'all') url.searchParams.set('view', view.value);
    status.textContent = 'Обновляем список…';
    results.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(url, {
        signal: pending.signal, credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error('Search failed');
      const document = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (current !== version) return;
      const next = document.getElementById('server-results');
      if (!next) {
        window.location.assign('/'); // Session expired: return to the login page.
        return;
      }
      results.replaceChildren(...next.childNodes);
      window.document.querySelector('.result-count').textContent =
        document.querySelector('.result-count').textContent;
      history.replaceState(null, '', url.pathname + url.search);
      status.textContent = '';
    } catch (error) {
      if (error.name !== 'AbortError' && current === version) {
        status.textContent = 'Не удалось обновить список. Повторите ввод или обновите страницу.';
      }
    } finally {
      if (current === version) results.removeAttribute('aria-busy');
    }
  }

  input.addEventListener('input', () => {
    if (pending) pending.abort();
    ++version;
    clearTimeout(timer);
    timer = setTimeout(search, 180);
  });
  view.addEventListener('change', search);
  form.addEventListener('submit', event => { event.preventDefault(); search(); });
})();

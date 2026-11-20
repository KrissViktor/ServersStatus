(() => {
  const key = 'serversstatus.theme';
  const root = document.documentElement;
  const choices = new Set(['system', 'light', 'dark']);
  function apply(value) {
    const theme = choices.has(value) ? value : 'system';
    root.dataset.theme = theme;
    for (const control of document.querySelectorAll('[data-theme-choice]')) control.value = theme;
  }
  try { apply(localStorage.getItem(key)); } catch (_) { apply('system'); }
  document.addEventListener('DOMContentLoaded', () => apply(root.dataset.theme));
  document.addEventListener('change', event => {
    if (!event.target.matches('[data-theme-choice]')) return;
    const theme = event.target.value;
    apply(theme);
    try { localStorage.setItem(key,theme); } catch (_) {}
  });
  window.addEventListener('storage', event => {
    if (event.key===key || event.key===null) apply(event.newValue);
  });
})();

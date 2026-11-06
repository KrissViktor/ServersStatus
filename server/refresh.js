(() => {
  if (!window.fetch) return;
  const targets = [...document.querySelectorAll('[data-refresh][id]')];
  if (!targets.length) return;
  let busy = false;
  setInterval(async () => {
    if (busy || document.hidden || (targets.some(target => target.contains(document.activeElement)) && document.activeElement.matches('input,select,textarea'))) return;
    busy = true;
    try {
      const response = await fetch(location.href, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      const next = new DOMParser().parseFromString(await response.text(), 'text/html');
      const x = scrollX, y = scrollY;
      document.body.style.minHeight = Math.max(innerHeight, y + innerHeight) + 'px';
      for (const target of targets) {
        const source = next.getElementById(target.id);
        if (source && source.innerHTML !== target.innerHTML) {
          const expanded = [...target.querySelectorAll('details')].map(detail => detail.open);
          [...source.querySelectorAll('details')].forEach((detail,index) => {
            if (index < expanded.length) detail.open = expanded[index];
          });
          target.innerHTML = source.innerHTML;
        }
      }
      window.scrollTo({left: x, top: y, behavior: 'instant'});
    } catch (_) {
      // Retain the last successful graph; retry on the next background tick.
    } finally { busy = false; }
  }, Math.min(...targets.map(target => Number(target.dataset.refreshInterval) || 10000)));
})();

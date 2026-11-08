(() => {
  if (!window.fetch) return;
  const targets = [...document.querySelectorAll('[data-refresh][id]')];
  if (!targets.length) return;
  let busy = false;
  setInterval(async () => {
    if (busy || document.hidden || targets.some(target=>target.dataset.fetchBusy==='true') || (targets.some(target => target.contains(document.activeElement)) && document.activeElement.matches('input,select,textarea'))) return;
    busy = true;
    try {
      const requested=location.href;
      const response = await fetch(requested, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      const next = new DOMParser().parseFromString(await response.text(), 'text/html');
      if(requested!==location.href || targets.some(target=>target.dataset.fetchBusy==='true'))return;
      const x = scrollX, y = scrollY;
      document.body.style.minHeight = Math.max(innerHeight, y + innerHeight) + 'px';
      for (const target of targets) {
        const source = next.getElementById(target.id);
        if (source && source.innerHTML !== target.innerHTML) {
          const key=detail=>detail.dataset.foldKey || detail.querySelector('summary')?.textContent.trim();
          const expanded = new Map([...target.querySelectorAll('details')].map(detail=>[key(detail),detail.open]));
          for (const detail of source.querySelectorAll('details'))if(expanded.has(key(detail)))detail.open=expanded.get(key(detail));
          target.innerHTML = source.innerHTML;
        }
      }
      window.scrollTo({left: x, top: y, behavior: 'instant'});
    } catch (_) {
      // Retain the last successful graph; retry on the next background tick.
    } finally { busy = false; }
  }, Math.min(...targets.map(target => Number(target.dataset.refreshInterval) || 10000)));
})();

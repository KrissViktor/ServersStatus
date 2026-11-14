const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function disk(path, url = '/servers/pc/forecast') {
  const result = {
    textContent: '', innerHTML: '', children: [],
    setAttribute() {}, removeAttribute() {}, append(node) { this.children.push(node); }
  };
  return {
    open: false, visible: true, isConnected: true, dataset: {forecastUrl: url, diskPath: path}, result,
    getClientRects() { return this.visible ? [{}] : []; }, querySelector() { return result; }
  };
}

(async () => {
  let nodes = [disk('C:'), disk('D:')], observe, toggle, now = 1000, fail = false;
  const requests = [];
  const document = {
    querySelectorAll: () => nodes,
    getElementById: () => ({closest: () => ({})}),
    addEventListener: (_, callback) => { toggle = callback; },
    createElement: () => ({addEventListener(_, callback) { this.click = callback; }})
  };
  vm.runInNewContext(fs.readFileSync('server/disk_forecast.js', 'utf8'), {
    document, Date: {now: () => now}, queueMicrotask, setTimeout, clearTimeout, AbortController,
    MutationObserver: class { constructor(callback) { observe = callback; } observe() {} },
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: !fail, json: async () => ({disks: {'C:': '<p>Forecast C</p>', 'D:': '<p>Forecast D</p>'}})};
    }
  });
  const settle = () => new Promise(resolve => setImmediate(resolve));
  await settle();
  assert.equal(requests.length, 0, 'Closed forecasts must not load');
  nodes.forEach(node => { node.open = true; }); toggle(); await settle();
  assert.equal(requests.length, 1, 'Disks share one in-flight request');
  assert.equal(nodes[0].result.innerHTML, '<p>Forecast C</p>');
  assert.equal(nodes[1].result.innerHTML, '<p>Forecast D</p>');
  assert.equal(requests[0].options.credentials, 'same-origin');
  nodes = [disk('C:')]; nodes[0].open = true; observe(); await settle();
  assert.equal(requests.length, 1, 'Background replacements reuse the cached forecast');
  assert.equal(nodes[0].result.innerHTML, '<p>Forecast C</p>');
  now += 61000;
  nodes = [disk('C:')]; nodes[0].open = true; observe(); await settle();
  assert.equal(requests.length, 2, 'An expired forecast is refreshed');
  fail = true;
  nodes = [disk('C:', '/servers/other/forecast')]; nodes[0].open = true; nodes[0].visible = false;
  observe(); await settle();
  assert.equal(requests.length, 2, 'Forecasts in hidden tabs must not load');
  nodes[0].visible = true; toggle(); await settle();
  assert.equal(nodes[0].dataset.forecastState, 'error');
  assert.match(nodes[0].result.textContent, /Не удалось/);
  fail = false; nodes[0].result.children[0].click(); await settle();
  assert.equal(nodes[0].dataset.forecastState, 'loaded');
  assert.equal(nodes[0].result.innerHTML, '<p>Forecast C</p>');
  console.log('On-demand disk forecasts, permissions mode, shared requests, refresh cache and retry: passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

// 王道 408 题库 Service Worker
// JS/CSS/HTML + 题库数据 JSON：Network-First（避免题干修了仍显示旧缓存）
// 其它同源静态：Stale-While-Revalidate

const CACHE_NAME = 'wd408-ui-v435';
const APP_SHELL = [
  './',
  './index.html',
  './styles.css?v=435',
  './app.js?v=435',
  './data.js?v=435',
  './manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k === CACHE_NAME ? null : caches.delete(k))))
    ).then(() => self.clients.claim())
  );
});

function isCodeOrShell(url) {
  const p = url.pathname || '';
  // 题库数据必须走网络优先，否则 OCR 修正后仍会长期显示旧题干
  if (p.endsWith('.js') || p.endsWith('.css') || p.endsWith('.html') || p.endsWith('.json')) return true;
  if (p.includes('data-ds') || p.includes('data-coa') || p.includes('data-net') || p.includes('data-os')) return true;
  if (p.endsWith('/banks/408') || p.endsWith('/banks/408/')) return true;
  // query-busted assets
  if (p.includes('/banks/408/') && (url.search.includes('v=') || p.endsWith('/'))) return true;
  return false;
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // API never cache
  if (url.pathname.startsWith('/api/')) return;

  if (url.origin === location.origin) {
    const p = url.pathname || '';
    // 题库 JSON/JS 数据包：只走网络、不写入 Cache，避免 OCR 修题后仍显示旧题干
    if (
      /data-(ds|coa|net|os)\.(json|js)$/.test(p) ||
      p.endsWith('/data.js') ||
      p.endsWith('/data.json')
    ) {
      event.respondWith(
        fetch(req, { cache: 'no-store' }).catch(() => caches.match(req))
      );
      return;
    }
    if (isCodeOrShell(url) || url.searchParams.has('v')) {
      // Network first for app code
      event.respondWith(
        fetch(req)
          .then((res) => {
            if (res && res.status === 200) {
              const copy = res.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
            }
            return res;
          })
          .catch(() => caches.match(req))
      );
      return;
    }
    // other same-origin: SWR
    event.respondWith(
      caches.match(req).then((cached) => {
        const fetchPromise = fetch(req)
          .then((res) => {
            if (res && res.status === 200 && (res.type === 'basic' || res.type === 'default')) {
              const copy = res.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
            }
            return res;
          })
          .catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  if (url.hostname.includes('jsdelivr.net') || url.hostname.includes('googleapis.com') || url.hostname.includes('gstatic.com')) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          }
          return res;
        });
      })
    );
  }
});

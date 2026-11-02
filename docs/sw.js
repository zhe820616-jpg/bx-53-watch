const CACHE="bx53-pwa-v1";
self.addEventListener("install",e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(["./","./index.html","./style.css","./app.js","./manifest.webmanifest","./icon.svg"]))));
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",e=>{const u=new URL(e.request.url);if(u.pathname.endsWith("/status.json"))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
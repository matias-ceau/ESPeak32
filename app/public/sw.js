// Offline app shell. Network first, so a new deployment is picked up as soon as the phone is online; every successful
// same-origin GET refreshes the cache, which serves the app when the network is unavailable.
const CACHE = "espeak32-shell";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg"];

// The built bundle has a hashed name, so it is found in index.html. Precaching it at install means the app also opens
// offline after a single visit (the page that registered the worker loaded its bundle before the worker existed).
const assetsOf = (html) => [...html.matchAll(/(?:src|href)="(\.\/assets\/[^"]+)"/g)].map((m) => m[1]);

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll(SHELL);
    const page = await c.match("./index.html");
    if (page) await c.addAll(assetsOf(await page.text()));
  })());
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())); // control the page that installed us, so its later requests are cached too
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
    }
    return res;
  // ignoreVary: servers may answer "Vary: Origin", and Chrome sends Origin with module-script requests but not with the
  // worker's own fetches, so without it the cached bundle never matches. Everything here is same-origin and static.
  }).catch(() => caches.match(e.request, { ignoreVary: true }).then((hit) => hit || Response.error())));
});

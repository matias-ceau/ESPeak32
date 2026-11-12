import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "vitest";

const SRC = readFileSync(fileURLToPath(new URL("../public/sw.js", import.meta.url)), "utf8");
const ORIGIN = "https://user.github.io";
const SCOPE = `${ORIGIN}/app/`;

/** Runs public/sw.js in a fake worker scope; returns its fetch and lifecycle handlers and the cache contents. */
function loadWorker(network: (r: Request) => Promise<Response>) {
  const handlers: Record<string, (e: any) => void> = {};
  const store = new Map<string, Response>();
  const key = (r: Request | string) => new URL(typeof r === "string" ? r : r.url, SCOPE).href;
  const cache = {
    match: async (r: Request | string) => store.get(key(r))?.clone(),
    put: async (r: Request | string, res: Response) => void store.set(key(r), res),
    addAll: async (urls: string[]) => {
      for (const u of urls) {
        const res = await network(new Request(key(u)));
        if (!res.ok) throw new TypeError(`addAll: ${u} failed`);
        store.set(key(u), res);
      }
    },
  };
  const caches = { open: async () => cache, match: async (r: Request) => cache.match(r), keys: async () => [], delete: async () => true };
  let claimed = false;
  const self = {
    addEventListener: (t: string, h: (e: any) => void) => (handlers[t] = h),
    skipWaiting: () => {},
    clients: { claim: async () => { claimed = true; } },
  };
  new Function("self", "caches", "fetch", "location", SRC)(self, caches, network, { origin: ORIGIN });
  const fetchVia = async (url: string) => {
    let p: Promise<Response> | undefined;
    handlers.fetch({ request: new Request(url), respondWith: (x: Promise<Response>) => (p = x) });
    return p ? await p : undefined;
  };
  const lifecycle = async (type: "install" | "activate") => {
    let p: Promise<unknown> = Promise.resolve();
    handlers[type]({ waitUntil: (x: Promise<unknown>) => (p = x) });
    await p;
  };
  return { fetchVia, lifecycle, store, claimed: () => claimed };
}

const BUILT_INDEX = `<!doctype html><html><head><link rel="manifest" href="./manifest.webmanifest" />
<script type="module" crossorigin src="./assets/index-CrQaf-FZ.js"></script>
<link rel="stylesheet" crossorigin href="./assets/index-B2x.css"></head><body></body></html>`;

test("a new deployment is served when online (no frozen app shell)", async () => {
  let version = "v1";
  const w = loadWorker(async () => new Response(version));
  expect(await (await w.fetchVia(`${SCOPE}`))!.text()).toBe("v1");
  version = "v2";
  expect(await (await w.fetchVia(`${SCOPE}`))!.text()).toBe("v2");
});

test("the cached shell is served offline", async () => {
  let online = true;
  const w = loadWorker(async () => (online ? new Response("shell") : Promise.reject(new TypeError("offline"))));
  await w.fetchVia(`${SCOPE}`);
  online = false;
  expect(await (await w.fetchVia(`${SCOPE}`))!.text()).toBe("shell");
});

test("install precaches the built bundle, so the app opens offline after one visit", async () => {
  let online = true;
  const w = loadWorker(async (r) => {
    if (!online) throw new TypeError("offline");
    return new Response(r.url.endsWith("index.html") || r.url === SCOPE ? BUILT_INDEX : `body of ${r.url}`);
  });
  await w.lifecycle("install");
  await w.lifecycle("activate");
  expect(w.claimed()).toBe(true);
  online = false;
  expect(await (await w.fetchVia(`${SCOPE}`))!.text()).toBe(BUILT_INDEX);
  expect(await (await w.fetchVia(`${SCOPE}assets/index-CrQaf-FZ.js`))!.text()).toBe(`body of ${SCOPE}assets/index-CrQaf-FZ.js`);
  expect(await (await w.fetchVia(`${SCOPE}assets/index-B2x.css`))!.text()).toBe(`body of ${SCOPE}assets/index-B2x.css`);
});

test("cross-origin requests are left to the browser", async () => {
  const w = loadWorker(async () => new Response("x"));
  expect(await w.fetchVia("https://openrouter.ai/api")).toBeUndefined();
});

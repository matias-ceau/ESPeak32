import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "vitest";

const SRC = readFileSync(fileURLToPath(new URL("../public/sw.js", import.meta.url)), "utf8");
const ORIGIN = "https://user.github.io";

/** Runs public/sw.js in a fake worker scope and returns its fetch handler. */
function loadWorker(network: (r: Request) => Promise<Response>) {
  const handlers: Record<string, (e: any) => void> = {};
  const store = new Map<string, Response>();
  const cache = {
    match: async (r: Request) => store.get(r.url)?.clone(),
    put: async (r: Request, res: Response) => void store.set(r.url, res),
    addAll: async () => {},
  };
  const caches = { open: async () => cache, match: async (r: Request) => cache.match(r), keys: async () => [], delete: async () => true };
  const self = { addEventListener: (t: string, h: (e: any) => void) => (handlers[t] = h), skipWaiting: () => {} };
  new Function("self", "caches", "fetch", "location", SRC)(self, caches, network, { origin: ORIGIN });
  const fetchVia = async (url: string) => {
    let p: Promise<Response> | undefined;
    handlers.fetch({ request: new Request(url), respondWith: (x: Promise<Response>) => (p = x) });
    return p ? await p : undefined;
  };
  return { fetchVia, store };
}

test("a new deployment is served when online (no frozen app shell)", async () => {
  let version = "v1";
  const w = loadWorker(async () => new Response(version));
  expect(await (await w.fetchVia(`${ORIGIN}/app/`))!.text()).toBe("v1");
  version = "v2";
  expect(await (await w.fetchVia(`${ORIGIN}/app/`))!.text()).toBe("v2");
});

test("the cached shell is served offline", async () => {
  let online = true;
  const w = loadWorker(async () => (online ? new Response("shell") : Promise.reject(new TypeError("offline"))));
  await w.fetchVia(`${ORIGIN}/app/`);
  online = false;
  expect(await (await w.fetchVia(`${ORIGIN}/app/`))!.text()).toBe("shell");
});

test("cross-origin requests are left to the browser", async () => {
  const w = loadWorker(async () => new Response("x"));
  expect(await w.fetchVia("https://openrouter.ai/api")).toBeUndefined();
});

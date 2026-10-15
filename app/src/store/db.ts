/** IndexedDB storage: synced notes, partial-note segments (resume across app restarts), clock pairs, settings. */
export interface NoteRecord {
  key: string; // "<file_id>:<boot_id>:<start_us>"
  fileId: number;
  bootId: number;
  startUs: bigint;
  codec: number;
  size: number;
  bytes: Uint8Array;
  wallMs: number | null;
  syncedAt: number;
}

const req = <T>(r: IDBRequest<T>) =>
  new Promise<T>((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });

export class Db {
  private constructor(private readonly idb: IDBDatabase) {}

  static open(name = "espeak32"): Promise<Db> {
    return new Promise((resolve, reject) => {
      const r = indexedDB.open(name, 1);
      r.onupgradeneeded = () => {
        const d = r.result;
        d.createObjectStore("notes", { keyPath: "key" });
        d.createObjectStore("segments", { keyPath: ["key", "offset"] });
        d.createObjectStore("clock", { keyPath: "bootId" });
        d.createObjectStore("settings", { keyPath: "name" });
      };
      r.onsuccess = () => resolve(new Db(r.result));
      r.onerror = () => reject(r.error);
    });
  }

  private store(name: string, mode: IDBTransactionMode = "readonly"): IDBObjectStore {
    return this.idb.transaction(name, mode).objectStore(name);
  }

  /** Resolves once the write is durable (transaction complete), which the two-phase delete relies on. */
  private write(name: string, fn: (s: IDBObjectStore) => void): Promise<void> {
    return new Promise((resolve, reject) => {
      const tx = this.idb.transaction(name, "readwrite");
      fn(tx.objectStore(name));
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  getNote(key: string): Promise<NoteRecord | undefined> {
    return req(this.store("notes").get(key));
  }

  putNote(n: NoteRecord): Promise<void> {
    return this.write("notes", (s) => s.put(n));
  }

  async listNotes(): Promise<NoteRecord[]> {
    const all: NoteRecord[] = await req(this.store("notes").getAll());
    return all.sort((a, b) => (b.wallMs ?? -Infinity) - (a.wallMs ?? -Infinity) || b.fileId - a.fileId);
  }

  appendSegment(key: string, offset: number, bytes: Uint8Array): Promise<void> {
    return this.write("segments", (s) => s.put({ key, offset, bytes }));
  }

  async segments(key: string): Promise<Uint8Array> {
    const range = IDBKeyRange.bound([key, 0], [key, Infinity]);
    const parts: Array<{ offset: number; bytes: Uint8Array }> = await req(this.store("segments").getAll(range));
    parts.sort((a, b) => a.offset - b.offset);
    const out = new Uint8Array(parts.reduce((n, p) => n + p.bytes.length, 0));
    let o = 0;
    for (const p of parts) { out.set(p.bytes, o); o += p.bytes.length; }
    return out;
  }

  clearSegments(key: string): Promise<void> {
    return this.write("segments", (s) => s.delete(IDBKeyRange.bound([key, 0], [key, Infinity])));
  }

  putClock(bootId: number, unixMs: number, ticksUs: bigint): Promise<void> {
    return this.write("clock", (s) => s.put({ bootId, unixMs, ticksUs }));
  }

  async clock(): Promise<Map<number, [number, bigint]>> {
    const all: Array<{ bootId: number; unixMs: number; ticksUs: bigint }> = await req(this.store("clock").getAll());
    return new Map(all.map((c) => [c.bootId, [c.unixMs, c.ticksUs]]));
  }

  async getSetting<T>(name: string, fallback: T): Promise<T> {
    const r: { value: T } | undefined = await req(this.store("settings").get(name));
    return r ? r.value : fallback;
  }

  setSetting(name: string, value: unknown): Promise<void> {
    return this.write("settings", (s) => s.put({ name, value }));
  }
}

/** Asks the browser not to evict our storage. With delete-after-sync, IndexedDB holds the only copy of a note. */
export async function requestPersistence(
  storage: StorageManager | undefined = globalThis.navigator?.storage,
): Promise<"persisted" | "best-effort" | "unsupported"> {
  if (!storage?.persist) return "unsupported";
  if (await storage.persisted()) return "persisted";
  return (await storage.persist()) ? "persisted" : "best-effort";
}

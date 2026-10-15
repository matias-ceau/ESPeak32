/** Resumable sync with two-phase delete; same rules as tools/espeak32/sync.py (PROTOCOL.md behaviour rules). */
import { parseE32 } from "../format/container";
import { crc32 } from "../format/crc32";
import { Db, type NoteRecord } from "../store/db";
import { wallMs } from "../time";
import * as P from "./protocol";
import { LinkLost, TimeoutError, type Transport } from "./transport";

const CTRL_TIMEOUT_MS = 5000;
const DONE_GRACE_MS = 200; // a stack may deliver TRANSFER_DONE ahead of the last chunks (CTRL and DATA are separate)
const MAX_RESUMES_PER_FETCH = 8;
const SEGMENT_BYTES = 64 * 1024;

export class SyncError extends Error {}
class NoteSkipped extends Error {}
class NoteBusy extends NoteSkipped {}
class CrcMismatch extends NoteSkipped {}
class DeviceReadFailed extends NoteSkipped {}
class KeepsLosingChunks extends NoteSkipped {}

export function noteKey(e: P.ListEntry): string {
  return `${e.fileId}:${e.bootId}:${e.startUs}`;
}

export interface SyncEvents {
  onStatus(text: string): void;
  onProgress(key: string, received: number, total: number): void;
  onNote(n: NoteRecord): void;
}

export interface SyncOptions {
  deleteAfterSync: boolean;
  nowMs: () => number;
  window?: number;
  attempts?: number;
  stallMs?: number;
  mtuRetryMs?: number;
}

export interface SyncReport {
  fetched: string[];
  deleted: number[];
  skipped: Array<[number, string]>;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Received bytes of one note: persisted segments plus a pending tail flushed every 64 KiB and on every stop. */
class NoteBuffer {
  private pending: Uint8Array[] = [];
  private pendingBytes = 0;

  constructor(private readonly db: Db, readonly key: string, public stored: number) {}

  get length(): number {
    return this.stored + this.pendingBytes;
  }

  async push(b: Uint8Array): Promise<void> {
    this.pending.push(b.slice());
    this.pendingBytes += b.length;
    if (this.pendingBytes >= SEGMENT_BYTES) await this.flush();
  }

  async flush(): Promise<void> {
    if (!this.pendingBytes) return;
    const seg = new Uint8Array(this.pendingBytes);
    let o = 0;
    for (const p of this.pending) { seg.set(p, o); o += p.length; }
    await this.db.appendSegment(this.key, this.stored, seg);
    this.stored += seg.length;
    this.pending = [];
    this.pendingBytes = 0;
  }
}

export class SyncClient {
  constructor(private readonly t: Transport, private readonly window = 16, private readonly stallMs = 5000,
              private readonly mtuRetryMs = 500) {
    if (window < 2) throw new RangeError("window must be at least 2");
  }

  private async nextCtrl(): Promise<P.CtrlMessage> {
    for (;;) {
      let ev;
      try {
        ev = await this.t.nextEvent(CTRL_TIMEOUT_MS);
      } catch (e) {
        if (e instanceof TimeoutError) throw new LinkLost("no response from device");
        throw e;
      }
      if (ev[0] === "ctrl") return P.decodeCtrl(ev[1]); // DATA left over from an aborted transfer is dropped
    }
  }

  private async request(req: Uint8Array): Promise<P.CtrlMessage> {
    for (let attempt = 0; ; attempt++) {
      await this.t.writeCtrl(req);
      const msg = await this.nextCtrl();
      if (msg.type === "error" && msg.status === P.STATUS_MTU) {
        if (attempt === 0) {
          await sleep(this.mtuRetryMs); // the first write can beat the MTU exchange
          continue;
        }
        throw new SyncError("The Bluetooth link MTU is below 64 bytes; this phone cannot sync with the device.");
      }
      return msg;
    }
  }

  async info(): Promise<P.Info> {
    return P.unpackInfo(await this.t.readInfo());
  }

  async setTime(unixMs: number): Promise<bigint> {
    const m = await this.request(P.reqSetTime(BigInt(unixMs)));
    if (m.type !== "setTimeAck") throw new SyncError(`unexpected SET_TIME answer ${m.type}`);
    return m.ticksUs;
  }

  async list(): Promise<P.ListEntry[]> {
    let m = await this.request(P.reqList());
    const out: P.ListEntry[] = [];
    for (;;) {
      if (m.type !== "list") throw new SyncError(`unexpected LIST answer ${m.type}`);
      if (m.total === 0) return [];
      out.push(m);
      if (out.length === m.total) return out;
      m = await this.nextCtrl();
    }
  }

  /** True if the device deleted the note or no longer has it; false if it is busy. */
  async delete(fileId: number): Promise<boolean> {
    const m = await this.request(P.reqDelete(fileId));
    if (m.type === "deleteAck") return true;
    if (m.type === "error" && m.status === P.STATUS_NOT_FOUND) return true;
    if (m.type === "error" && m.status === P.STATUS_BUSY) return false;
    throw new SyncError(`unexpected DELETE answer ${m.type}`);
  }

  private async abort(): Promise<void> {
    await this.t.writeCtrl(P.reqAbort());
    while ((await this.nextCtrl()).type !== "abortAck") { /* skip stale messages */ }
  }

  /** Fetches a note, resuming from its stored segments; returns the verified bytes. */
  async fetch(entry: P.ListEntry, db: Db, onProgress: (received: number) => void): Promise<Uint8Array> {
    const key = noteKey(entry);
    let resumes = 0;
    for (;;) {
      let offset = (await db.segments(key)).length;
      if (offset > entry.size) {
        await db.clearSegments(key);
        offset = 0;
      }
      const m = await this.request(P.reqGet(entry.fileId, offset, this.window));
      if (m.type === "error") {
        if (m.status === P.STATUS_BUSY) throw new NoteBusy();
        if (m.status === P.STATUS_BAD_ARGS && offset) { await db.clearSegments(key); continue; }
        if (m.status === P.STATUS_IO) throw new DeviceReadFailed();
        throw new SyncError(`GET of note ${entry.fileId} failed with status ${m.status}`);
      }
      if (m.type !== "getAck" || m.fileId !== entry.fileId) throw new SyncError(`unexpected GET answer ${m.type}`);
      const buf = new NoteBuffer(db, key, offset);
      let done: P.CtrlMessage | null;
      try {
        done = await this.receive(buf, m.totalSize, onProgress);
      } finally {
        await buf.flush();
      }
      if (done && done.type === "transferDone") {
        const data = await db.segments(key);
        let ok = crc32(data) === done.fileCrc32;
        try { parseE32(data); } catch { ok = false; }
        if (!ok) {
          await db.clearSegments(key);
          throw new CrcMismatch();
        }
        return data;
      }
      if (++resumes > MAX_RESUMES_PER_FETCH) {
        await this.abort();
        throw new KeepsLosingChunks();
      }
      await this.abort();
    }
  }

  /** Appends chunks until TRANSFER_DONE (returned) or a gap or stall (null: the caller resumes). */
  private async receive(buf: NoteBuffer, size: number, onProgress: (n: number) => void): Promise<P.CtrlMessage | null> {
    const half = this.window >> 1;
    let expectedSeq = 0, consumed = 0, linkOk = true;
    let done: P.CtrlMessage | null = null; // arrived before the last chunks
    for (;;) {
      let ev;
      try {
        ev = await this.t.nextEvent(done ? DONE_GRACE_MS : this.stallMs);
      } catch (e) {
        if (e instanceof TimeoutError) return null;
        throw e;
      }
      if (ev[0] === "ctrl") {
        const m = P.decodeCtrl(ev[1]);
        if (m.type === "transferFailed") throw new DeviceReadFailed();
        if (m.type === "transferDone") {
          if (buf.length === size) return m;
          done = m;
        }
        continue;
      }
      const { seq, payload } = P.unpackDataChunk(ev[1]);
      if (seq !== expectedSeq) return null;
      await buf.push(payload);
      onProgress(buf.length);
      if (done && buf.length === size) return done;
      expectedSeq = (expectedSeq + 1) & 0xffff;
      if (++consumed >= half && linkOk) {
        consumed = 0;
        try {
          await this.t.writeCtrl(P.reqCredit(half));
        } catch (e) {
          if (!(e instanceof LinkLost)) throw e;
          linkOk = false; // keep the chunks already queued; nextEvent reports the loss
        }
      }
    }
  }
}

async function fetchVerified(c: SyncClient, e: P.ListEntry, db: Db, onProgress: (n: number) => void): Promise<Uint8Array | string> {
  for (let retried = false; ; retried = true) {
    try {
      return await c.fetch(e, db, onProgress);
    } catch (err) {
      if (err instanceof NoteBusy) return "busy (recording)";
      if (err instanceof CrcMismatch && retried) return "crc mismatch after refetch";
      if (err instanceof DeviceReadFailed && retried) return "read failure on device";
      if (err instanceof KeepsLosingChunks) return "transfer keeps losing chunks";
      if (!(err instanceof NoteSkipped)) throw err;
    }
  }
}

async function syncOnce(t: Transport, db: Db, o: Required<SyncOptions>, ev: SyncEvents, rep: SyncReport): Promise<void> {
  const c = new SyncClient(t, o.window, o.stallMs, o.mtuRetryMs);
  const info = await c.info();
  const unixMs = o.nowMs();
  await db.putClock(info.bootId, unixMs, await c.setTime(unixMs));
  const clock = await db.clock();
  const entries = await c.list();
  ev.onStatus(entries.length ? `${entries.length} note(s) on the device` : "No notes on the device");
  for (const e of entries) {
    const key = noteKey(e);
    const have = await db.getNote(key);
    if (!have || have.size !== e.size) {
      ev.onStatus(`Fetching note ${e.fileId}…`);
      const r = await fetchVerified(c, e, db, (n) => ev.onProgress(key, n, e.size));
      if (typeof r === "string") {
        if (!rep.skipped.some(([id, why]) => id === e.fileId && why === r)) rep.skipped.push([e.fileId, r]);
        continue;
      }
      const note: NoteRecord = { key, fileId: e.fileId, bootId: e.bootId, startUs: e.startUs, codec: e.codec,
        size: e.size, bytes: r, wallMs: wallMs(e.bootId, e.startUs, clock), syncedAt: o.nowMs() };
      await db.putNote(note); // durable before DELETE: two-phase delete
      await db.clearSegments(key);
      if (!rep.fetched.includes(key)) rep.fetched.push(key);
      ev.onNote(note);
    }
    if (o.deleteAfterSync && (await c.delete(e.fileId)) && !rep.deleted.includes(e.fileId)) rep.deleted.push(e.fileId);
  }
}

export async function syncAll(connect: () => Promise<Transport>, db: Db, opts: SyncOptions, ev: SyncEvents): Promise<SyncReport> {
  const o: Required<SyncOptions> = { window: 16, attempts: 3, stallMs: 5000, mtuRetryMs: 500, ...opts };
  const rep: SyncReport = { fetched: [], deleted: [], skipped: [] };
  for (let i = 0; i < o.attempts; i++) {
    if (i) ev.onStatus("Link lost; reconnecting to resume…");
    const t = await connect();
    try {
      await syncOnce(t, db, o, ev, rep);
      return rep;
    } catch (e) {
      if (!(e instanceof LinkLost)) throw e;
    } finally {
      await t.close();
    }
  }
  throw new SyncError(`link lost ${o.attempts} times; partial notes are kept and the next sync resumes them`);
}

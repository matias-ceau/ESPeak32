/** TypeScript port of tools/espeak32/device_model.py (checked against protocol/vectors/sync.txt) and a Transport
 *  over it with fault injection. Test-only. */
import { crc32 } from "../src/format/crc32";
import * as P from "../src/ble/protocol";
import { LinkLost, TimeoutError, type LinkEvent, type Transport } from "../src/ble/transport";

export interface DeviceConfig {
  bootId: number;
  fw: [number, number, number];
  codecsMask: number;
  batteryPct: number;
  freeBytes: number;
  nowUs: bigint;
}

const DEFAULTS: DeviceConfig = { bootId: 5, fw: [0, 2, 0], codecsMask: 3, batteryPct: 255, freeBytes: 2_500_000,
  nowUs: 1_000_000n };
const ARG_BYTES: Record<number, number> = { 1: 0, 2: 10, 3: 2, 4: 4, 5: 8, 6: 0 };
const MAX_PAYLOAD = 507;

interface Xfer { fileId: number; size: number; offset: number; credits: number; crc: number; seq: number }

export class MockDevice {
  notes: Map<number, Uint8Array>;
  busy: Map<number, Uint8Array>;
  config: DeviceConfig;
  outputs: Array<["ctrl" | "data", Uint8Array]> = [];
  failReadAt: [number, number] | null = null;
  private mtu = 23;
  private connected = false;
  private xfer: Xfer | null = null;

  constructor(notes: Map<number, Uint8Array>, config: Partial<DeviceConfig> = {}, busy = new Map<number, Uint8Array>()) {
    this.notes = new Map(notes);
    this.busy = new Map(busy);
    this.config = { ...DEFAULTS, ...config };
  }

  connect(mtu: number): void { this.connected = true; this.mtu = mtu; this.xfer = null; }
  setMtu(mtu: number): void { this.mtu = mtu; }
  disconnect(): void { this.connected = false; this.xfer = null; }

  info(): Uint8Array {
    const c = this.config, b = new Uint8Array(26), v = new DataView(b.buffer);
    b.set([1, c.batteryPct, ...c.fw, c.codecsMask]);
    v.setUint32(6, c.freeBytes, true);
    v.setUint32(10, c.bootId, true);
    v.setBigUint64(14, c.nowUs, true);
    v.setUint32(22, this.notes.size, true);
    return b;
  }

  private ctrl(bytes: number[] | Uint8Array): void { this.outputs.push(["ctrl", Uint8Array.from(bytes)]); }
  private status(op: number, s: number): void { this.ctrl([op | 0x80, s]); }
  private readFails(id: number, start: number, end: number): boolean {
    const f = this.failReadAt;
    return f !== null && f[0] === id && start <= f[1] && f[1] < end;
  }

  request(req: Uint8Array): void {
    if (!this.connected || req.length === 0) return;
    const op = req[0], args = new DataView(req.buffer, req.byteOffset + 1, req.length - 1);
    if (op === P.OP_CREDIT) {
      if (args.byteLength === 2 && this.xfer) this.xfer.credits = Math.min(0xffff, this.xfer.credits + args.getUint16(0, true));
      return;
    }
    if (!(op in ARG_BYTES)) return this.status(op, P.STATUS_UNKNOWN_OPCODE);
    if (this.mtu < 64) return this.status(op, P.STATUS_MTU);
    if (args.byteLength !== ARG_BYTES[op]) return this.status(op, P.STATUS_BAD_ARGS);
    if (op === P.OP_LIST) this.list();
    else if (op === P.OP_GET) this.get(args.getUint32(0, true), args.getUint32(4, true), args.getUint16(8, true));
    else if (op === P.OP_DELETE) this.delete(args.getUint32(0, true));
    else if (op === P.OP_SET_TIME) {
      const b = new Uint8Array(10);
      b.set([0x80 | P.OP_SET_TIME, 0]);
      new DataView(b.buffer).setBigUint64(2, this.config.nowUs, true);
      this.ctrl(b);
    } else {
      this.xfer = null;
      this.ctrl([0x80 | P.OP_ABORT, 0]);
    }
  }

  private list(): void {
    const ids = [...this.notes.keys()].sort((a, b) => a - b);
    if (ids.length === 0) return this.ctrl([0x81, 0, 0, 0, 0, 0]);
    ids.forEach((id, i) => {
      const data = this.notes.get(id)!;
      const b = new Uint8Array(27), v = new DataView(b.buffer);
      b.set([0x81, 0]);
      v.setUint16(2, i, true);
      v.setUint16(4, ids.length, true);
      v.setUint32(6, id, true);
      v.setUint32(10, data.length, true);
      const hv = new DataView(data.buffer, data.byteOffset);
      const ok = data.length >= 32 && new TextDecoder().decode(data.subarray(0, 4)) === "E32A" && data[4] === 1;
      b[14] = ok ? data[5] : 255;
      v.setUint32(15, ok ? hv.getUint32(12, true) : 0, true);
      v.setBigUint64(19, ok ? hv.getBigUint64(16, true) : 0n, true);
      this.ctrl(b);
    });
  }

  private get(id: number, offset: number, credits: number): void {
    if (this.busy.has(id)) return this.status(P.OP_GET, P.STATUS_BUSY);
    const data = this.notes.get(id);
    if (!data) return this.status(P.OP_GET, P.STATUS_NOT_FOUND);
    if (offset > data.length) return this.status(P.OP_GET, P.STATUS_BAD_ARGS);
    this.xfer = null;
    if (this.readFails(id, 0, offset)) return this.status(P.OP_GET, P.STATUS_IO);
    this.xfer = { fileId: id, size: data.length, offset, credits, crc: crc32(data.subarray(0, offset)), seq: 0 };
    const b = new Uint8Array(10), v = new DataView(b.buffer);
    b.set([0x82, 0]);
    v.setUint32(2, id, true);
    v.setUint32(6, data.length, true);
    this.ctrl(b);
  }

  private delete(id: number): void {
    if (this.busy.has(id) || this.xfer?.fileId === id) return this.status(P.OP_DELETE, P.STATUS_BUSY);
    if (!this.notes.has(id)) return this.status(P.OP_DELETE, P.STATUS_NOT_FOUND);
    this.notes.delete(id);
    const b = new Uint8Array(6);
    b.set([0x84, 0]);
    new DataView(b.buffer).setUint32(2, id, true);
    this.ctrl(b);
  }

  pump(): boolean {
    const x = this.xfer;
    if (!this.connected || !x) return false;
    if (x.offset === x.size) {
      this.xfer = null;
      const b = new Uint8Array(10), v = new DataView(b.buffer);
      b.set([P.EV_TRANSFER_DONE, 0]);
      v.setUint32(2, x.fileId, true);
      v.setUint32(6, x.crc, true);
      this.ctrl(b);
      return true;
    }
    if (x.credits === 0) return false;
    const n = Math.min(this.mtu - 5, MAX_PAYLOAD, x.size - x.offset);
    if (this.readFails(x.fileId, x.offset, x.offset + n)) {
      this.xfer = null;
      this.ctrl([P.EV_TRANSFER_DONE, P.STATUS_IO]);
      return true;
    }
    const chunk = this.notes.get(x.fileId)!.subarray(x.offset, x.offset + n);
    const b = new Uint8Array(2 + n);
    b.set([x.seq & 0xff, x.seq >> 8]);
    b.set(chunk, 2);
    this.outputs.push(["data", b]);
    x.crc = crc32(chunk, x.crc);
    x.offset += n;
    x.seq = (x.seq + 1) & 0xffff;
    x.credits--;
    return true;
  }

  runUntilIdle(): void {
    while (this.pump()) { /* drain */ }
  }
}

export interface MockTransportOptions {
  mtu?: number;
  dropAfterChunks?: number;
  dropChunk?: number;
  /** Lose the chunk with this seq on every GET. */
  dropSeq?: number;
  corrupt?: (seq: number) => boolean;
  dropOnOp?: number;
  /** Deliver TRANSFER_DONE ahead of the transfer's last DATA chunk. */
  doneEarly?: boolean;
  dropBefore?: boolean;
}

/** Mirrors tools/espeak32/sync.py ModelTransport; the device runs synchronously on each write. */
export class MockTransport implements Transport {
  writes: Uint8Array[] = [];
  dataSeen = 0;
  dataDelivered = 0;
  private events: LinkEvent[] = [];
  private closed = false;
  private dropOnOp: number | undefined;

  constructor(readonly dev: MockDevice, private readonly opts: MockTransportOptions = {}) {
    this.dropOnOp = opts.dropOnOp;
    dev.outputs.length = 0;
    dev.connect(opts.mtu ?? 247);
  }

  private drop(): void {
    this.closed = true;
    this.dev.disconnect();
    this.dev.outputs.length = 0;
  }

  private collect(): void {
    this.dev.runUntilIdle();
    for (const [ch, m0] of this.dev.outputs) {
      if (this.closed) break;
      let m = m0;
      if (ch === "data") {
        const idx = this.dataSeen++;
        if (this.opts.dropAfterChunks !== undefined && idx >= this.opts.dropAfterChunks) {
          this.drop();
          break;
        }
        const seq = m[0] | (m[1] << 8);
        if (idx === this.opts.dropChunk || seq === this.opts.dropSeq) continue;
        if (this.opts.corrupt && m.length > 2 && this.opts.corrupt(seq)) {
          m = m.slice();
          m[2] ^= 1;
        }
        this.dataDelivered++;
      }
      if (this.opts.doneEarly && ch === "ctrl" && m[0] === P.EV_TRANSFER_DONE && this.events.at(-1)?.[0] === "data") {
        this.events.splice(this.events.length - 1, 0, [ch, m]);
        continue;
      }
      this.events.push([ch, m]);
    }
    this.dev.outputs.length = 0;
  }

  async readInfo(): Promise<Uint8Array> {
    if (this.closed) throw new LinkLost("closed");
    return this.dev.info();
  }

  async writeCtrl(b: Uint8Array): Promise<void> {
    if (this.closed) throw new LinkLost("closed");
    this.writes.push(b);
    if (this.dropOnOp !== undefined && b[0] === this.dropOnOp) {
      this.dropOnOp = undefined;
      if (this.opts.dropBefore === false) this.dev.request(b);
      this.drop();
      throw new LinkLost("dropped on write");
    }
    this.dev.request(b);
    this.collect();
  }

  async nextEvent(_timeoutMs: number): Promise<LinkEvent> {
    const ev = this.events.shift();
    if (ev) return ev;
    if (this.closed) throw new LinkLost("closed");
    throw new TimeoutError();
  }

  async close(): Promise<void> {
    if (!this.closed) {
      this.closed = true;
      this.dev.disconnect();
    }
  }
}

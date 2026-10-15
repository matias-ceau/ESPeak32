import "fake-indexeddb/auto";
import { describe, expect, test } from "vitest";
import * as P from "../src/ble/protocol";
import { syncAll, type SyncOptions } from "../src/ble/syncClient";
import { unpackHeader } from "../src/format/container";
import { Db } from "../src/store/db";
import { MockDevice, MockTransport, type MockTransportOptions } from "./mockDevice";
import { vector } from "./vectors";

const TONE = vector("tone_16k.adpcm.e32");
const EMPTY = vector("empty.e32");
const NOW = 1_700_000_000_000;
let dbn = 0;

const device = () => new MockDevice(new Map([[1, TONE], [2, EMPTY]]));
const keyOf = (id: number, data: Uint8Array) => {
  const h = unpackHeader(data);
  return `${id}:${h.bootId}:${h.startUs}`;
};

function connector(dev: MockDevice, first: MockTransportOptions[] = [], rest: MockTransportOptions = {}) {
  const made: MockTransport[] = [];
  const connect = async () => {
    const t = new MockTransport(dev, { mtu: 64, ...(made.length < first.length ? first[made.length] : rest) });
    made.push(t);
    return t;
  };
  return Object.assign(connect, { made });
}

async function run(dev: MockDevice, opts: Partial<SyncOptions> & { connect?: ReturnType<typeof connector>; db?: Db } = {}) {
  const db = opts.db ?? (await Db.open(`s${dbn++}`));
  const status: string[] = [];
  const rep = await syncAll(opts.connect ?? connector(dev), db,
    { deleteAfterSync: true, nowMs: () => NOW, mtuRetryMs: 0, ...opts },
    { onStatus: (s) => status.push(s), onProgress: () => {}, onNote: () => {} });
  return { rep, db, status };
}

describe("syncAll", () => {
  test("two notes byte-exact, then deleted", async () => {
    const dev = device();
    const { rep, db } = await run(dev);
    expect((await db.getNote(keyOf(1, TONE)))!.bytes).toEqual(TONE);
    expect((await db.getNote(keyOf(2, EMPTY)))!.bytes).toEqual(EMPTY);
    expect(rep.fetched).toEqual([keyOf(1, TONE), keyOf(2, EMPTY)]);
    expect(rep.deleted).toEqual([1, 2]);
    expect(dev.notes.size).toBe(0);
    expect((await db.getNote(keyOf(1, TONE)))!.wallMs).toBeNull(); // recorded in boot 2; the device is in boot 5
  });

  test("wall time is set for notes from the current boot", async () => {
    const dev = new MockDevice(new Map([[1, TONE]]), { bootId: 2, nowUs: 0x0102030405060708n + 5_000_000n });
    const { db } = await run(dev);
    expect((await db.getNote(keyOf(1, TONE)))!.wallMs).toBe(NOW - 5000);
  });

  test("keeps notes on the device when deleteAfterSync is off", async () => {
    const dev = device();
    const { rep } = await run(dev, { deleteAfterSync: false });
    expect(rep.deleted).toEqual([]);
    expect(dev.notes.size).toBe(2);
  });

  test("delete only after putNote", async () => {
    const dev = device();
    const db = await Db.open(`s${dbn++}`);
    const seen: boolean[] = [];
    const real = dev.request.bind(dev);
    dev.request = (req) => {
      if (req[0] === P.OP_DELETE) {
        const id = req[1];
        void db.getNote(keyOf(id, dev.notes.get(id)!)).then((n) => seen.push(n !== undefined));
      }
      real(req);
    };
    await run(dev, { db });
    await new Promise((r) => setTimeout(r, 20));
    expect(seen).toEqual([true, true]);
  });

  test.each([1, 70, 140])("resumes after a drop at chunk %i", async (dropAt) => {
    const dev = device();
    const connect = connector(dev, [{ dropAfterChunks: dropAt }]);
    const { rep, db } = await run(dev, { connect });
    expect((await db.getNote(keyOf(1, TONE)))!.bytes).toEqual(TONE);
    expect(rep.fetched.length).toBe(2);
    expect(Array.from(connect.made[1].writes[2])).toEqual(Array.from(P.reqGet(1, dropAt * 59, 16)));
  });

  test("lost chunk detected by seq and refetched", async () => {
    const dev = device();
    const { rep, db } = await run(dev, { connect: connector(dev, [{ dropChunk: 5 }]) });
    expect((await db.getNote(keyOf(1, TONE)))!.bytes).toEqual(TONE);
    expect(rep.fetched.length).toBe(2);
  });

  test("CRC mismatch refetches once then skips and never deletes", async () => {
    const dev = device();
    const { rep, db } = await run(dev, { connect: connector(dev, [], { corrupt: (seq) => seq === 3 }) });
    expect(rep.skipped).toEqual([[1, "crc mismatch after refetch"]]);
    expect(dev.notes.has(1)).toBe(true);
    expect(await db.getNote(keyOf(1, TONE))).toBeUndefined();
  });

  test("device read failure retried once then skipped", async () => {
    const dev = device();
    dev.failReadAt = [1, 2000];
    const { rep } = await run(dev);
    expect(rep.skipped).toEqual([[1, "read failure on device"]]);
    expect(dev.notes.has(1)).toBe(true);
  });

  test("busy note skipped, the rest syncs", async () => {
    const dev = device();
    const real = dev.request.bind(dev);
    dev.request = (req) => (req[0] === P.OP_GET && req[1] === 2 ? dev.outputs.push(["ctrl", new Uint8Array([0x82, P.STATUS_BUSY])]) && undefined : real(req));
    const { rep } = await run(dev);
    expect(rep.skipped).toEqual([[2, "busy (recording)"]]);
    expect(dev.notes.has(2)).toBe(true);
  });

  test("MTU too small fails fast without reconnecting", async () => {
    const dev = device();
    const connect = connector(dev, [], { mtu: 23 });
    await expect(run(dev, { connect })).rejects.toThrow(/MTU/);
    expect(connect.made.length).toBe(1);
  });

  test("skips refetch of a note already stored", async () => {
    const dev = device();
    const connect = connector(dev, [{ dropOnOp: P.OP_DELETE }]);
    const { rep } = await run(dev, { connect });
    expect(dev.notes.size).toBe(0);
    expect(rep.deleted).toEqual([1, 2]);
    expect(connect.made[1].dataDelivered).toBe(1); // only the empty note
  });

  test("resumes from persisted segments across runs", async () => {
    const dev = device();
    const db = await Db.open(`s${dbn++}`);
    await expect(run(dev, { db, connect: connector(dev, [{ dropAfterChunks: 50 }]), attempts: 1 })).rejects.toThrow(/link lost/);
    expect((await db.segments(keyOf(1, TONE))).length).toBe(50 * 59);
    const connect = connector(dev);
    await run(dev, { db, connect });
    expect((await db.getNote(keyOf(1, TONE)))!.bytes).toEqual(TONE);
    expect((await db.segments(keyOf(1, TONE))).length).toBe(0);
    expect(connect.made[0].dataDelivered).toBe(141 - 50 + 1);
  });

  test("credit policy: GET with 16, CREDIT(8) every 8 chunks", async () => {
    const dev = new MockDevice(new Map([[1, TONE]]));
    const connect = connector(dev);
    await run(dev, { connect, deleteAfterSync: false });
    const w = connect.made[0].writes;
    const get = w.findIndex((x) => x[0] === P.OP_GET);
    expect(Array.from(w[get].subarray(9))).toEqual([16, 0]);
    const credits = w.slice(get + 1).filter((x) => x[0] === P.OP_CREDIT);
    expect(credits.length).toBe(Math.floor(141 / 8));
    credits.forEach((c) => expect(Array.from(c)).toEqual(Array.from(P.reqCredit(8))));
  });

  test("a reused file id with a new header is a new note", async () => {
    const dev = device();
    const db = await Db.open(`s${dbn++}`);
    await run(dev, { db, deleteAfterSync: false });
    const renamed = TONE.slice();
    new DataView(renamed.buffer).setUint32(12, 99, true); // new boot_id, same file id
    const dev2 = new MockDevice(new Map([[1, renamed]]));
    const { rep } = await run(dev2, { db });
    expect(rep.fetched).toEqual([keyOf(1, renamed)]);
    expect((await db.listNotes()).length).toBe(3);
  });
});

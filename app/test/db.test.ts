import "fake-indexeddb/auto";
import { expect, test } from "vitest";
import { Db, type NoteRecord } from "../src/store/db";
import { noteKey } from "../src/ble/syncClient";

let n = 0;
const fresh = () => Db.open(`t${n++}`);
const note = (fileId: number, wallMs: number | null): NoteRecord => ({ key: `${fileId}:1:0`, fileId, bootId: 1,
  startUs: 0n, codec: 1, size: 3, bytes: new Uint8Array([1, 2, 3]), wallMs, syncedAt: 1 });

test("notes roundtrip and list newest first", async () => {
  const db = await fresh();
  await db.putNote(note(1, 1000));
  await db.putNote(note(2, 3000));
  await db.putNote(note(3, null));
  expect((await db.getNote("2:1:0"))?.startUs).toBe(0n);
  expect((await db.listNotes()).map((x) => x.fileId)).toEqual([2, 1, 3]);
  expect(await db.getNote("9:9:9")).toBeUndefined();
});

test("segments concatenate in offset order and clear", async () => {
  const db = await fresh();
  await db.appendSegment("k", 3, new Uint8Array([4, 5]));
  await db.appendSegment("k", 0, new Uint8Array([1, 2, 3]));
  await db.appendSegment("other", 0, new Uint8Array([9]));
  expect(Array.from(await db.segments("k"))).toEqual([1, 2, 3, 4, 5]);
  await db.clearSegments("k");
  expect((await db.segments("k")).length).toBe(0);
  expect(Array.from(await db.segments("other"))).toEqual([9]);
});

test("clock and settings", async () => {
  const db = await fresh();
  await db.putClock(5, 1000, 7n);
  await db.putClock(5, 2000, 9n);
  expect(await db.clock()).toEqual(new Map([[5, [2000, 9n]]]));
  expect(await db.getSetting("deleteAfterSync", true)).toBe(true);
  await db.setSetting("deleteAfterSync", false);
  expect(await db.getSetting("deleteAfterSync", true)).toBe(false);
});

test("note key includes boot and start", () => {
  expect(noteKey({ type: "list", index: 0, total: 1, fileId: 7, size: 1, codec: 1, bootId: 3, startUs: 42n })).toBe("7:3:42");
});

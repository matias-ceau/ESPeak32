import { describe, expect, test } from "vitest";
import * as P from "../src/ble/protocol";
import { vectorText } from "./vectors";

type Vec = { name: string; hex: string; decoded: Record<string, unknown> | null };
const VECS: Vec[] = JSON.parse(vectorText("ble.json"));
const hex = (b: Uint8Array) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
const bytes = (h: string) => new Uint8Array(h.match(/../g)!.map((x) => parseInt(x, 16)));
const byName = (n: string) => VECS.find((v) => v.name === n)!;

describe("requests match ble.json", () => {
  test.each([
    ["req_list", P.reqList()],
    ["req_get", P.reqGet(7, 0x100, 8)],
    ["req_credit", P.reqCredit(3)],
    ["req_delete", P.reqDelete(9)],
    ["req_set_time", P.reqSetTime(0x0102030405060708n)],
    ["req_abort", P.reqAbort()],
  ])("%s", (name, built) => expect(hex(built as Uint8Array)).toBe(byName(name as string).hex));
});

describe("CTRL notifications decode as in ble.json", () => {
  const expected: Record<string, (d: any) => P.CtrlMessage> = {
    ctrl_ListEntry: (d) => ({ type: "list", index: d.index, total: d.total, fileId: d.file_id, size: d.size,
      codec: d.codec, bootId: d.boot_id, startUs: BigInt(d.start_us) }),
    ctrl_GetAck: (d) => ({ type: "getAck", fileId: d.file_id, totalSize: d.total_size }),
    ctrl_DeleteAck: (d) => ({ type: "deleteAck", fileId: d.file_id }),
    ctrl_SetTimeAck: (d) => ({ type: "setTimeAck", ticksUs: BigInt(d.ticks_us) }),
    ctrl_AbortAck: () => ({ type: "abortAck" }),
    ctrl_TransferDone: (d) => ({ type: "transferDone", fileId: d.file_id, fileCrc32: d.file_crc32 }),
    ctrl_TransferFailed: (d) => ({ type: "transferFailed", status: d.status }),
    ctrl_ErrorAck: (d) => ({ type: "error", op: d.op, status: d.status }),
  };
  const ctrl = VECS.filter((v) => v.name.startsWith("ctrl_"));
  test("every message type is covered", () => {
    expect(new Set(ctrl.map((v) => v.name))).toEqual(new Set(Object.keys(expected)));
  });
  test.each(ctrl.map((v) => [v.name, v] as const))("%s (%#)", (name, v) => {
    expect(P.decodeCtrl(bytes(v.hex))).toEqual(expected[name](v.decoded));
  });
  test("rejects short and unknown", () => {
    expect(() => P.decodeCtrl(bytes("82"))).toThrow(P.ProtocolError);
    expect(() => P.decodeCtrl(bytes("8200"))).toThrow(P.ProtocolError);
    expect(() => P.decodeCtrl(bytes("ff00"))).toThrow(P.ProtocolError);
  });
});

test("INFO decodes", () => {
  const v = byName("info");
  const d = v.decoded as any;
  expect(P.unpackInfo(bytes(v.hex))).toEqual({ protoVersion: d.proto_version, batteryPct: d.battery_pct, fw: d.fw,
    codecsMask: d.codecs_mask, freeBytes: d.free_bytes, bootId: d.boot_id, ticksUs: BigInt(d.ticks_us),
    fileCount: d.file_count });
  expect(() => P.unpackInfo(bytes(v.hex).subarray(1))).toThrow(P.ProtocolError);
});

test("DATA chunk", () => {
  const c = P.unpackDataChunk(bytes(byName("data_chunk").hex));
  expect(c.seq).toBe(65535);
  expect(hex(c.payload)).toBe("6162");
});

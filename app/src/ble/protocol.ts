/** BLE message codec (protocol/PROTOCOL.md); golden messages in protocol/vectors/ble.json. */
export const SERVICE_UUID = "8f05e6c5-7b93-4a53-b175-b3416b3a0d20";
export const INFO_UUID = "8f05e6c6-7b93-4a53-b175-b3416b3a0d20";
export const CTRL_UUID = "8f05e6c7-7b93-4a53-b175-b3416b3a0d20";
export const DATA_UUID = "8f05e6c8-7b93-4a53-b175-b3416b3a0d20";

export const OP_LIST = 1, OP_GET = 2, OP_CREDIT = 3, OP_DELETE = 4, OP_SET_TIME = 5, OP_ABORT = 6;
export const EV_TRANSFER_DONE = 0x83;
export const STATUS_OK = 0, STATUS_UNKNOWN_OPCODE = 1, STATUS_BAD_ARGS = 2, STATUS_NOT_FOUND = 3, STATUS_BUSY = 4,
  STATUS_MTU = 5, STATUS_IO = 6;

export class ProtocolError extends Error {}

export interface Info {
  protoVersion: number;
  batteryPct: number; // 255 = unknown
  fw: [number, number, number];
  codecsMask: number;
  freeBytes: number;
  bootId: number;
  ticksUs: bigint;
  fileCount: number;
}

export interface ListEntry {
  type: "list";
  index: number;
  total: number;
  fileId: number;
  size: number;
  codec: number;
  bootId: number;
  startUs: bigint;
}

export type CtrlMessage =
  | ListEntry
  | { type: "getAck"; fileId: number; totalSize: number }
  | { type: "deleteAck"; fileId: number }
  | { type: "setTimeAck"; ticksUs: bigint }
  | { type: "abortAck" }
  | { type: "transferDone"; fileId: number; fileCrc32: number }
  | { type: "transferFailed"; status: number }
  | { type: "error"; op: number; status: number };

const view = (b: Uint8Array) => new DataView(b.buffer, b.byteOffset, b.byteLength);

export function unpackInfo(b: Uint8Array): Info {
  if (b.length !== 26) throw new ProtocolError("bad INFO length");
  const v = view(b);
  return {
    protoVersion: b[0], batteryPct: b[1], fw: [b[2], b[3], b[4]], codecsMask: b[5],
    freeBytes: v.getUint32(6, true), bootId: v.getUint32(10, true), ticksUs: v.getBigUint64(14, true),
    fileCount: v.getUint32(22, true),
  };
}

function req(op: number, size: number, fill?: (v: DataView) => void): Uint8Array {
  const b = new Uint8Array(1 + size);
  b[0] = op;
  fill?.(new DataView(b.buffer, 1));
  return b;
}

export const reqList = () => req(OP_LIST, 0);
export const reqGet = (fileId: number, offset: number, credits: number) =>
  req(OP_GET, 10, (v) => { v.setUint32(0, fileId, true); v.setUint32(4, offset, true); v.setUint16(8, credits, true); });
export const reqCredit = (credits: number) => req(OP_CREDIT, 2, (v) => v.setUint16(0, credits, true));
export const reqDelete = (fileId: number) => req(OP_DELETE, 4, (v) => v.setUint32(0, fileId, true));
export const reqSetTime = (unixMs: bigint) => req(OP_SET_TIME, 8, (v) => v.setBigUint64(0, unixMs, true));
export const reqAbort = () => req(OP_ABORT, 0);

function body(b: Uint8Array, size: number): DataView {
  if (b.length !== size) throw new ProtocolError("bad body length");
  return view(b);
}

export function decodeCtrl(msg: Uint8Array): CtrlMessage {
  if (msg.length < 2 || !(msg[0] & 0x80)) throw new ProtocolError("bad CTRL notification");
  const op = msg[0] & 0x7f, status = msg[1], b = msg.subarray(2);
  if (op < OP_LIST || op > OP_ABORT) throw new ProtocolError(`unknown opcode ${op}`);
  if (status !== STATUS_OK) {
    // 0x83 is the TRANSFER_DONE event (CREDIT has no response): a non-zero status means the transfer failed
    return op === OP_CREDIT ? { type: "transferFailed", status } : { type: "error", op, status };
  }
  switch (op) {
    case OP_LIST: {
      if (b.length === 4) {
        if (view(b).getUint16(2, true) !== 0) throw new ProtocolError("bad body length");
        return { type: "list", index: 0, total: 0, fileId: 0, size: 0, codec: 0, bootId: 0, startUs: 0n };
      }
      const v = body(b, 25);
      return { type: "list", index: v.getUint16(0, true), total: v.getUint16(2, true), fileId: v.getUint32(4, true),
        size: v.getUint32(8, true), codec: v.getUint8(12), bootId: v.getUint32(13, true),
        startUs: v.getBigUint64(17, true) };
    }
    case OP_GET: {
      const v = body(b, 8);
      return { type: "getAck", fileId: v.getUint32(0, true), totalSize: v.getUint32(4, true) };
    }
    case OP_CREDIT: {
      const v = body(b, 8);
      return { type: "transferDone", fileId: v.getUint32(0, true), fileCrc32: v.getUint32(4, true) };
    }
    case OP_DELETE:
      return { type: "deleteAck", fileId: body(b, 4).getUint32(0, true) };
    case OP_SET_TIME:
      return { type: "setTimeAck", ticksUs: body(b, 8).getBigUint64(0, true) };
    default:
      body(b, 0);
      return { type: "abortAck" };
  }
}

export function unpackDataChunk(b: Uint8Array): { seq: number; payload: Uint8Array } {
  if (b.length < 2) throw new ProtocolError("chunk too short");
  return { seq: b[0] | (b[1] << 8), payload: b.subarray(2) };
}

/** `.e32` container (protocol/FILE_FORMAT.md). Version 1 finalizes in the header; version 2 (firmware >= 0.3.0) appends
 *  an end record `[u16 0xFFFF]["E32E"][u32 sample_count][u32 payload_crc32]`. Both are read. */
import { crc32 } from "./crc32";

export const HEADER_BYTES = 32;
export const UNFINALIZED = 0xffffffff;
export const END_MARKER = 0xffff;
export const END_BYTES = 14;
export const CODEC_PCM16 = 0;
export const CODEC_ADPCM = 1;

export class FormatError extends Error {}

export interface Header {
  version: number;
  codec: number;
  sampleRate: number;
  fileId: number;
  bootId: number;
  startUs: bigint;
  sampleCount: number; // version 2: always UNFINALIZED (see E32File.sampleCount)
  payloadCrc32: number; // version 2: always 0
}

export interface E32File {
  header: Header;
  frames: Uint8Array[];
  finalized: boolean;
  crcOk: boolean | null;
  truncated: boolean;
  /** From the header (v1) or the end record (v2); UNFINALIZED if not finalized. */
  sampleCount: number;
  /** 0 if not finalized. */
  payloadCrc32: number;
}

export function unpackHeader(data: Uint8Array): Header {
  if (data.length < HEADER_BYTES) throw new FormatError("short header");
  const v = new DataView(data.buffer, data.byteOffset, HEADER_BYTES);
  if (new TextDecoder().decode(data.subarray(0, 4)) !== "E32A") throw new FormatError("bad magic");
  const version = v.getUint8(4);
  if (version !== 1 && version !== 2) throw new FormatError(`unsupported version ${version}`);
  return {
    version,
    codec: v.getUint8(5),
    sampleRate: v.getUint16(6, true),
    fileId: v.getUint32(8, true),
    bootId: v.getUint32(12, true),
    startUs: v.getBigUint64(16, true),
    sampleCount: v.getUint32(24, true),
    payloadCrc32: v.getUint32(28, true),
  };
}

const isEndMagic = (d: Uint8Array, at: number) => d[at] === 0x45 && d[at + 1] === 0x33 && d[at + 2] === 0x32 && d[at + 3] === 0x45;

/** Parses a note; a trailing partial frame is ignored (truncated) and excluded from the CRC, as in FILE_FORMAT.md.
 *  Mirrors tools/espeak32/container.py. */
export function parseE32(data: Uint8Array): E32File {
  const header = unpackHeader(data);
  const frames: Uint8Array[] = [];
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  let pos = HEADER_BYTES;
  let end: [number, number] | null = null;
  let payloadEnd = -1;
  while (pos + 2 <= data.length) {
    const n = data[pos] | (data[pos + 1] << 8);
    if (n === END_MARKER && header.version >= 2) {
      if (pos + END_BYTES <= data.length && isEndMagic(data, pos + 2)) {
        end = [view.getUint32(pos + 6, true), view.getUint32(pos + 10, true)];
        payloadEnd = pos;
        pos += END_BYTES;
      }
      break; // an incomplete or garbled end record leaves the note unfinalized
    }
    if (pos + 2 + n > data.length) break;
    frames.push(data.subarray(pos + 2, pos + 2 + n));
    pos += 2 + n;
  }
  const truncated = pos !== data.length;
  let finalized: boolean, count: number, crc: number;
  if (header.version === 1) {
    finalized = header.sampleCount !== UNFINALIZED;
    [count, crc, payloadEnd] = [header.sampleCount, header.payloadCrc32, pos];
  } else {
    finalized = end !== null;
    [count, crc] = end ?? [UNFINALIZED, 0];
  }
  const crcOk = finalized ? crc32(data.subarray(HEADER_BYTES, payloadEnd)) === crc : null;
  return { header, frames, finalized, crcOk, truncated, sampleCount: finalized ? count : UNFINALIZED,
    payloadCrc32: finalized ? crc : 0 };
}

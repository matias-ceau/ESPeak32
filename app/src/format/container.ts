import { crc32 } from "./crc32";

export const HEADER_BYTES = 32;
export const UNFINALIZED = 0xffffffff;
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
  sampleCount: number;
  payloadCrc32: number;
}

export interface E32File {
  header: Header;
  frames: Uint8Array[];
  finalized: boolean;
  crcOk: boolean | null;
  truncated: boolean;
}

export function unpackHeader(data: Uint8Array): Header {
  if (data.length < HEADER_BYTES) throw new FormatError("short header");
  const v = new DataView(data.buffer, data.byteOffset, HEADER_BYTES);
  if (new TextDecoder().decode(data.subarray(0, 4)) !== "E32A") throw new FormatError("bad magic");
  const version = v.getUint8(4);
  if (version !== 1) throw new FormatError(`unsupported version ${version}`);
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

/** Parses a note; a trailing partial frame is ignored (truncated) and excluded from the CRC, as in FILE_FORMAT.md. */
export function parseE32(data: Uint8Array): E32File {
  const header = unpackHeader(data);
  const frames: Uint8Array[] = [];
  let pos = HEADER_BYTES;
  while (pos + 2 <= data.length) {
    const n = data[pos] | (data[pos + 1] << 8);
    if (pos + 2 + n > data.length) break;
    frames.push(data.subarray(pos + 2, pos + 2 + n));
    pos += 2 + n;
  }
  const finalized = header.sampleCount !== UNFINALIZED;
  const crcOk = finalized ? crc32(data.subarray(HEADER_BYTES, pos)) === header.payloadCrc32 : null;
  return { header, frames, finalized, crcOk, truncated: pos !== data.length };
}

import { describe, expect, test } from "vitest";
import { adpcmDecode } from "../src/format/adpcm";
import { FormatError, HEADER_BYTES, parseE32 } from "../src/format/container";
import { crc32 } from "../src/format/crc32";
import { decodeE32 } from "../src/format/decode";
import { wavBytes } from "../src/format/wav";
import { fixture, vector, vectorText } from "./vectors";

const int16 = (b: Uint8Array) => new Int16Array(b.buffer, b.byteOffset, b.byteLength / 2);

describe("crc32", () => {
  test("check value", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
  });
  test("chaining equals one call", () => {
    const d = new TextEncoder().encode("123456789");
    expect(crc32(d.subarray(4), crc32(d.subarray(0, 4)))).toBe(0xcbf43926);
  });
});

describe("container", () => {
  const manifest = JSON.parse(vectorText("manifest.json")).files as Array<{
    name: string;
    finalized: boolean;
    payload_crc32: string;
    sample_count: number;
  }>;
  test.each(manifest.filter((f) => f.finalized))("$name matches the manifest", (f) => {
    const e = parseE32(vector(f.name));
    expect(e.header.payloadCrc32).toBe(Number(f.payload_crc32));
    expect(e.header.sampleCount).toBe(f.sample_count);
    expect(e.crcOk).toBe(true);
    expect(e.finalized).toBe(true);
  });
  test("header fields", () => {
    const h = parseE32(vector("tone_16k.adpcm.e32")).header;
    expect(h).toMatchObject({ version: 1, codec: 1, sampleRate: 16000, fileId: 1, bootId: 2 });
    expect(h.startUs).toBe(0x0102030405060708n);
  });
  test("unfinalized vector", () => {
    const e = parseE32(vector("tone_16k.unfinalized.e32"));
    expect(e.finalized).toBe(false);
    expect(e.truncated).toBe(true);
    expect(e.crcOk).toBeNull();
  });
  test("rejects bad input", () => {
    const good = vector("empty.e32");
    expect(() => parseE32(good.subarray(0, HEADER_BYTES - 1))).toThrow(FormatError);
    const badMagic = good.slice();
    badMagic[0] = 0x58;
    expect(() => parseE32(badMagic)).toThrow(FormatError);
    const badVersion = good.slice();
    badVersion[4] = 2;
    expect(() => parseE32(badVersion)).toThrow(FormatError);
  });
});

describe("decode", () => {
  test("ADPCM decode is bit-exact with the Python reference", () => {
    const r = decodeE32(vector("tone_16k.adpcm.e32"));
    expect(r.sampleRate).toBe(16000);
    expect(Array.from(r.samples)).toEqual(Array.from(int16(fixture("tone_adpcm_decoded.pcm"))));
    expect(r.warnings).toEqual([]);
  });
  test("ADPCM keeps every block's first sample exact and SNR >= 20 dB", () => {
    const pcm = int16(vector("tone_16k.pcm"));
    const out = decodeE32(vector("tone_16k.adpcm.e32")).samples;
    for (let i = 0; i < pcm.length; i += 505) expect(out[i]).toBe(pcm[i]);
    let sig = 0, err = 0;
    pcm.forEach((v, i) => { sig += v * v; err += (v - out[i]) ** 2; });
    expect(10 * Math.log10(sig / err)).toBeGreaterThanOrEqual(20);
  });
  test("PCM16 decode is exact", () => {
    expect(Array.from(decodeE32(vector("tone_16k.pcm16.e32")).samples)).toEqual(Array.from(int16(vector("tone_16k.pcm"))));
  });
  test("empty note", () => {
    const r = decodeE32(vector("empty.e32"));
    expect(r.samples.length).toBe(0);
    expect(r.warnings).toContain("empty recording");
  });
  test("unfinalized note decodes available blocks with warnings", () => {
    const r = decodeE32(vector("tone_16k.unfinalized.e32"));
    expect(r.samples.length % 505).toBe(0);
    expect(r.warnings.join(" ")).toMatch(/not finalized/);
    expect(r.warnings.join(" ")).toMatch(/truncated/);
  });
  test("adpcmDecode trims to the sample count", () => {
    const blocks = parseE32(vector("tone_16k.adpcm.e32")).frames;
    expect(adpcmDecode(blocks, 1000).length).toBe(1000);
  });
});

describe("wav", () => {
  test("16-bit mono header", () => {
    const w = wavBytes(new Int16Array([1, -2, 3]), 16000);
    const v = new DataView(w.buffer);
    const s = (o: number, n: number) => new TextDecoder().decode(w.subarray(o, o + n));
    expect(s(0, 4)).toBe("RIFF");
    expect(s(8, 4)).toBe("WAVE");
    expect(v.getUint32(4, true)).toBe(w.length - 8);
    expect(v.getUint16(22, true)).toBe(1); // channels
    expect(v.getUint32(24, true)).toBe(16000);
    expect(v.getUint16(34, true)).toBe(16); // bits
    expect(v.getUint32(40, true)).toBe(6);
    expect(v.getInt16(46, true)).toBe(-2);
  });
});

import { describe, expect, test } from "vitest";
import { adpcmDecode } from "../src/format/adpcm";
import { END_BYTES, FormatError, HEADER_BYTES, parseE32, UNFINALIZED } from "../src/format/container";
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
    version: number;
    finalized: boolean;
    payload_crc32: string;
    sample_count: number;
  }>;
  test("vectors cover format versions 1 and 2", () => {
    expect(new Set(manifest.map((f) => f.version))).toEqual(new Set([1, 2]));
  });
  test.each(manifest)("$name matches the manifest", (f) => {
    const e = parseE32(vector(f.name));
    expect(e.header.version).toBe(f.version);
    expect(e.finalized).toBe(f.finalized);
    if (f.finalized) {
      expect(e.payloadCrc32).toBe(Number(f.payload_crc32));
      expect(e.sampleCount).toBe(f.sample_count);
      expect(e.crcOk).toBe(true);
    }
  });
  test("header fields", () => {
    const h = parseE32(vector("tone_16k.adpcm.e32")).header;
    expect(h).toMatchObject({ version: 2, codec: 1, sampleRate: 16000, fileId: 1, bootId: 2, sampleCount: UNFINALIZED });
    expect(h.startUs).toBe(0x0102030405060708n);
  });
  test.each(["tone_16k.unfinalized.e32", "v1/tone_16k.unfinalized.e32"])("unfinalized vector %s", (name) => {
    const e = parseE32(vector(name));
    expect(e.finalized).toBe(false);
    expect(e.truncated).toBe(true);
    expect(e.crcOk).toBeNull();
  });
  test("a cut end record leaves the note unfinalized", () => {
    const full = vector("tone_16k.adpcm.e32");
    for (let cut = 1; cut < END_BYTES; cut++) {
      const e = parseE32(full.subarray(0, full.length - cut));
      expect(e.finalized).toBe(false);
      expect(e.truncated).toBe(true);
      expect(e.frames.length).toBe(parseE32(full).frames.length);
    }
  });
  test("a garbled end record leaves the note unfinalized", () => {
    const d = vector("tone_16k.adpcm.e32").slice();
    d[d.length - 11] ^= 1; // inside "E32E"
    expect(parseE32(d).finalized).toBe(false);
  });
  test("payload corruption is detected in both versions", () => {
    for (const name of ["tone_16k.adpcm.e32", "v1/tone_16k.adpcm.e32"]) {
      const d = vector(name).slice();
      d[40] ^= 1;
      expect(parseE32(d).crcOk).toBe(false);
    }
  });
  test("rejects bad input", () => {
    const good = vector("empty.e32");
    expect(() => parseE32(good.subarray(0, HEADER_BYTES - 1))).toThrow(FormatError);
    const badMagic = good.slice();
    badMagic[0] = 0x58;
    expect(() => parseE32(badMagic)).toThrow(FormatError);
    const badVersion = good.slice();
    badVersion[4] = 3;
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
  test.each(["tone_16k.adpcm.e32", "tone_16k.pcm16.e32", "tone_16k.unfinalized.e32"])(
    "v1 note %s decodes like its v2 twin", (name) => {
      const v2 = decodeE32(vector(name)), v1 = decodeE32(vector("v1/" + name));
      expect(Array.from(v1.samples)).toEqual(Array.from(v2.samples));
      expect(v1.warnings).toEqual(v2.warnings);
      expect(v1.crcOk).toBe(v2.crcOk);
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

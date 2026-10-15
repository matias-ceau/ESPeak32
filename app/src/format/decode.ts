import { adpcmDecode, BLOCK_SAMPLES } from "./adpcm";
import { CODEC_ADPCM, CODEC_PCM16, FormatError, parseE32 } from "./container";

export interface Decoded {
  sampleRate: number;
  samples: Int16Array;
  warnings: string[];
  crcOk: boolean | null;
}

/** Mirrors tools/espeak32/decode.py. */
export function decodeE32(data: Uint8Array): Decoded {
  const f = parseE32(data);
  const warnings: string[] = [];
  const pcmBytes = f.frames.reduce((s, fr) => s + fr.length, 0);
  let count: number;
  if (f.finalized) count = f.header.sampleCount;
  else {
    warnings.push("file not finalized (recording was interrupted)");
    count = f.header.codec === CODEC_ADPCM ? f.frames.length * BLOCK_SAMPLES : pcmBytes >> 1;
  }
  if (f.truncated) warnings.push("truncated trailing frame ignored");
  let samples: Int16Array;
  if (f.header.codec === CODEC_ADPCM) samples = adpcmDecode(f.frames, count);
  else if (f.header.codec === CODEC_PCM16) {
    const all = new Uint8Array(pcmBytes);
    let o = 0;
    for (const fr of f.frames) { all.set(fr, o); o += fr.length; }
    samples = new Int16Array(all.buffer, 0, Math.min(count, pcmBytes >> 1));
  } else throw new FormatError(`codec ${f.header.codec} is not supported`);
  if (samples.length === 0) warnings.push("empty recording");
  return { sampleRate: f.header.sampleRate, samples, warnings, crcOk: f.crcOk };
}

/** IMA-ADPCM decoder for WAVE 0x11 mono blocks (256 bytes, 505 samples), reference IMA arithmetic. */
export const BLOCK_SAMPLES = 505;

const STEP = [
  7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107,
  118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
  1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894,
  6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
  32767,
];
const INDEX_ADJ = [-1, -1, -1, -1, 2, 4, 6, 8];

export function adpcmDecode(blocks: Uint8Array[], sampleCount: number): Int16Array {
  const out = new Int16Array(blocks.length * BLOCK_SAMPLES);
  let n = 0;
  for (const b of blocks) {
    let pred = (b[0] | (b[1] << 8)) << 16 >> 16;
    let index = Math.min(b[2], 88);
    out[n++] = pred;
    for (let i = 4; i < b.length; i++) {
      for (const code of [b[i] & 15, b[i] >> 4]) {
        const step = STEP[index];
        let d = step >> 3;
        if (code & 4) d += step;
        if (code & 2) d += step >> 1;
        if (code & 1) d += step >> 2;
        pred = Math.max(-32768, Math.min(32767, code & 8 ? pred - d : pred + d));
        index = Math.max(0, Math.min(88, index + INDEX_ADJ[code & 7]));
        out[n++] = pred;
      }
    }
  }
  return out.subarray(0, Math.min(sampleCount, n));
}

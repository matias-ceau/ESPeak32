/** Wall time of a note (PROTOCOL.md rule 13): latest SET_TIME pair recorded for the same boot, floor division. */
export function wallMs(bootId: number, startUs: bigint, clock: Map<number, [number, bigint]>): number | null {
  const pair = clock.get(bootId);
  if (!pair) return null;
  const diff = startUs - pair[1];
  const ms = diff >= 0n ? diff / 1000n : -((-diff + 999n) / 1000n); // BigInt division truncates; floor it
  return pair[0] + Number(ms);
}

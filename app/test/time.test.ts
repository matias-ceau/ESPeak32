import { expect, test } from "vitest";
import { wallMs } from "../src/time";

const NOW = 1_700_000_000_000;
test("wall time from the latest SET_TIME pair of the same boot", () => {
  const clock = new Map([[5, [NOW, 1_000_000n] as [number, bigint]]]);
  expect(wallMs(5, 3_000_000n, clock)).toBe(NOW + 2000);
  expect(wallMs(5, 0n, clock)).toBe(NOW - 1000);
  expect(wallMs(5, 1_000_999n, clock)).toBe(NOW); // floor, as in Python's //
  expect(wallMs(5, 999_999n, clock)).toBe(NOW - 1);
  expect(wallMs(6, 0n, clock)).toBeNull();
});

import { expect, test } from "vitest";
import { MockDevice } from "./mockDevice";
import { vector, vectorText } from "./vectors";

const hex = (b: Uint8Array) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
const bytes = (h: string) => new Uint8Array((h.match(/../g) ?? []).map((x) => parseInt(x, 16)));

/** Same harness rules as firmware/core/test/test_xfer.c. */
test("MockDevice replays every sync.txt scenario byte for byte", () => {
  let scenarios = 0;
  let dev: MockDevice | null = null;
  let notes = new Map<number, Uint8Array>(), busy = new Map<number, Uint8Array>();
  let config: Record<string, unknown> = {};
  let failRead: [number, number] | null = null;
  let outs: Array<[string, string]> = [];
  let checked = 0;
  let name = "";
  const device = () => {
    if (!dev) {
      dev = new MockDevice(notes, config, busy);
      dev.failReadAt = failRead;
    }
    return dev;
  };
  const act = (fn: (d: MockDevice) => void) => {
    expect(checked, `${name}: unexpected extra output`).toBe(outs.length);
    const d = device();
    d.outputs.length = 0;
    fn(d);
    d.runUntilIdle();
    outs = d.outputs.map(([ch, m]) => [ch.toUpperCase(), hex(m)]);
    checked = 0;
  };
  for (const line of vectorText("sync.txt").split("\n")) {
    const [kw, a, b] = line.split(" ");
    if (kw === "SCENARIO") {
      name = a; dev = null; notes = new Map(); busy = new Map(); failRead = null; outs = []; checked = 0;
    } else if (kw === "CONFIG") {
      const kv = Object.fromEntries(line.split(" ").slice(1).map((p) => p.split("=")));
      config = { bootId: +kv.boot_id, fw: kv.fw.split(".").map(Number), codecsMask: +kv.codecs,
        batteryPct: +kv.battery, freeBytes: +kv.free, nowUs: BigInt(kv.now_us) };
    } else if (kw === "FILE") notes.set(+a, vector(b));
    else if (kw === "BUSY") busy.set(+a, vector(b));
    else if (kw === "FAILREAD") failRead = [+a, +b];
    else if (kw === "CONNECT") act((d) => d.connect(+a));
    else if (kw === "MTU") act((d) => d.setMtu(+a));
    else if (kw === "SEND") act((d) => d.request(bytes(a)));
    else if (kw === "DISCONNECT") act((d) => d.disconnect());
    else if (kw === "INFO") {
      act(() => {});
      outs = [["INFO", hex(device().info())]];
    } else if (kw === "EXPECT") {
      expect(outs[checked], `${name}: missing output`).toBeDefined();
      expect(outs[checked++], name).toEqual([a, b]);
    } else if (kw === "END") {
      expect(checked, `${name}: unexpected extra output`).toBe(outs.length);
      scenarios++;
    } else if (line) throw new Error(`unknown directive ${line}`);
  }
  expect(scenarios).toBeGreaterThanOrEqual(20);
});

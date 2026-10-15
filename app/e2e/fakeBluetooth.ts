/** Fake Web Bluetooth device for the e2e test, backed by the unit tests' MockDevice and the committed vectors.
 *  Drops the link once after 20 DATA chunks (the tone is 35 chunks at MTU 247). Loaded only by e2e/sync.spec.ts through the Vite dev server. */
import { MockDevice } from "../test/mockDevice";
import { CTRL_UUID, DATA_UUID, INFO_UUID, SERVICE_UUID } from "../src/ble/protocol";
import toneUrl from "../../protocol/vectors/tone_16k.adpcm.e32?url";
import emptyUrl from "../../protocol/vectors/empty.e32?url";

const load = async (u: string) => new Uint8Array(await (await fetch(u)).arrayBuffer());
const dev = new MockDevice(new Map([[1, await load(toneUrl)], [2, await load(emptyUrl)]]));
const DROP_AFTER_DATA = 20;
let dataSent = 0, dropped = false, connections = 0;

class Characteristic extends EventTarget {
  value: DataView | null = null;
  constructor(readonly uuid: string, private readonly server: Server) { super(); }
  async readValue(): Promise<DataView> {
    this.server.check();
    return new DataView(dev.info().buffer);
  }
  async writeValueWithResponse(v: BufferSource): Promise<void> {
    this.server.check();
    const b = v instanceof ArrayBuffer ? new Uint8Array(v) : new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
    dev.request(b.slice());
    dev.runUntilIdle();
    const outs = dev.outputs.splice(0);
    setTimeout(() => this.server.deliver(outs), 0);
  }
  async startNotifications(): Promise<this> { return this; }
  async stopNotifications(): Promise<this> { return this; }
}

class Server {
  connected = false;
  chars = new Map<string, Characteristic>();
  constructor(private readonly device: FakeDevice) {
    for (const u of [INFO_UUID, CTRL_UUID, DATA_UUID]) this.chars.set(u, new Characteristic(u, this));
  }
  check(): void { if (!this.connected) throw new DOMException("GATT Server is disconnected.", "NetworkError"); }
  async connect(): Promise<this> {
    this.connected = true;
    connections++;
    dev.connect(247);
    return this;
  }
  disconnect(): void {
    if (!this.connected) return;
    this.connected = false;
    dev.disconnect();
    this.device.dispatchEvent(new Event("gattserverdisconnected"));
  }
  async getPrimaryService(uuid: string) {
    if (uuid !== SERVICE_UUID) throw new DOMException("No service", "NotFoundError");
    return { getCharacteristic: async (c: string) => this.chars.get(c)! };
  }
  deliver(outs: Array<["ctrl" | "data", Uint8Array]>): void {
    for (const [ch, msg] of outs) {
      if (!this.connected) return;
      if (ch === "data" && !dropped && ++dataSent > DROP_AFTER_DATA) {
        dropped = true;
        this.disconnect();
        return;
      }
      const c = this.chars.get(ch === "ctrl" ? CTRL_UUID : DATA_UUID)!;
      c.value = new DataView(msg.slice().buffer);
      c.dispatchEvent(new Event("characteristicvaluechanged"));
    }
  }
}

class FakeDevice extends EventTarget {
  id = "fake-1";
  name = "ESPeak32";
  gatt = new Server(this);
}

const device = new FakeDevice();
export const fake = {
  requestDevice: async (_o: unknown) => device,
  getDevices: async () => [device],
};
(window as any).__espeak32Fake = { stats: () => ({ notesLeft: dev.notes.size, connections }) };

/** Transport over Web Bluetooth (Chrome on Android). */
import { CTRL_UUID, DATA_UUID, INFO_UUID, SERVICE_UUID } from "./protocol";
import { LinkLost, TimeoutError, type LinkEvent, type Transport } from "./transport";

let lastDevice: BluetoothDevice | null = null; // reconnecting after a drop must not need a new user gesture

const bytesOf = (v: DataView) => new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength));

class WebBluetoothTransport implements Transport {
  private events: LinkEvent[] = [];
  private waiter: (() => void) | null = null;
  private lost = false;

  constructor(private readonly device: BluetoothDevice, private readonly info: BluetoothRemoteGATTCharacteristic,
              private readonly ctrl: BluetoothRemoteGATTCharacteristic,
              private readonly data: BluetoothRemoteGATTCharacteristic) {
    ctrl.addEventListener("characteristicvaluechanged", this.onCtrl);
    data.addEventListener("characteristicvaluechanged", this.onData);
    device.addEventListener("gattserverdisconnected", this.onLost);
  }

  private wake(): void {
    this.waiter?.();
    this.waiter = null;
  }
  private onCtrl = () => { this.events.push(["ctrl", bytesOf(this.ctrl.value!)]); this.wake(); };
  private onData = () => { this.events.push(["data", bytesOf(this.data.value!)]); this.wake(); };
  private onLost = () => { this.lost = true; this.wake(); };

  private async gatt<T>(op: () => Promise<T>): Promise<T> {
    if (this.lost) throw new LinkLost("disconnected");
    try {
      return await op();
    } catch (e) {
      if (this.lost || !this.device.gatt?.connected) throw new LinkLost(String(e));
      throw e;
    }
  }

  async readInfo(): Promise<Uint8Array> {
    return bytesOf(await this.gatt(() => this.info.readValue()));
  }

  async writeCtrl(b: Uint8Array): Promise<void> {
    await this.gatt(() => this.ctrl.writeValueWithResponse(new Uint8Array(b)));
  }

  async nextEvent(timeoutMs: number): Promise<LinkEvent> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const ev = this.events.shift();
      if (ev) return ev;
      if (this.lost) throw new LinkLost("disconnected");
      const left = deadline - Date.now();
      if (left <= 0) throw new TimeoutError();
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, left);
        this.waiter = () => { clearTimeout(timer); resolve(); };
      });
    }
  }

  async close(): Promise<void> {
    this.ctrl.removeEventListener("characteristicvaluechanged", this.onCtrl);
    this.data.removeEventListener("characteristicvaluechanged", this.onData);
    this.device.removeEventListener("gattserverdisconnected", this.onLost);
    if (this.device.gatt?.connected) this.device.gatt.disconnect();
  }
}

async function pickDevice(reuse: boolean): Promise<BluetoothDevice> {
  if (lastDevice) return lastDevice;
  if (reuse && "getDevices" in navigator.bluetooth) {
    const known = await navigator.bluetooth.getDevices(); // experimental in Chrome; falls back to the chooser
    if (known.length) return (lastDevice = known[0]);
  }
  return (lastDevice = await navigator.bluetooth.requestDevice({ filters: [{ services: [SERVICE_UUID] }] }));
}

export async function connectWebBluetooth(opts: { reuse: boolean }): Promise<Transport> {
  if (!("bluetooth" in navigator)) throw new Error("Web Bluetooth is not available: use Chrome on Android over HTTPS.");
  const device = await pickDevice(opts.reuse);
  const server = await device.gatt!.connect();
  const service = await server.getPrimaryService(SERVICE_UUID);
  const [info, ctrl, data] = await Promise.all([INFO_UUID, CTRL_UUID, DATA_UUID].map((u) => service.getCharacteristic(u)));
  const t = new WebBluetoothTransport(device, info, ctrl, data);
  await ctrl.startNotifications();
  await data.startNotifications();
  return t;
}

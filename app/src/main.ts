import { connectWebBluetooth } from "./ble/webBluetooth";
import { Db } from "./store/db";
import { mountView } from "./ui/view";

const db = await Db.open();
await mountView(document.getElementById("app")!, { db, connect: (reuse) => connectWebBluetooth({ reuse }) });

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(() => { /* offline shell is optional */ });
}

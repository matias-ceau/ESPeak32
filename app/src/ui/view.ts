/** The single M2 screen: connect & sync, progress, delete-after-sync toggle, synced notes with Play and Save WAV. */
import { syncAll } from "../ble/syncClient";
import type { Transport } from "../ble/transport";
import { BLOCK_SAMPLES } from "../format/adpcm";
import { CODEC_ADPCM, parseE32 } from "../format/container";
import { decodeE32 } from "../format/decode";
import { wavBytes } from "../format/wav";
import { requestPersistence, type Db, type NoteRecord } from "../store/db";

export interface ViewDeps {
  db: Db;
  connect: (reuse: boolean) => Promise<Transport>;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, unknown> = {},
                                                   ...kids: Array<Node | string>): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  Object.assign(e, props);
  e.append(...kids);
  return e;
}

function durationS(bytes: Uint8Array): number {
  try {
    const f = parseE32(bytes);
    const n = f.finalized ? f.header.sampleCount
      : f.header.codec === CODEC_ADPCM ? f.frames.length * BLOCK_SAMPLES : f.frames.reduce((s, x) => s + x.length, 0) / 2;
    return n / f.header.sampleRate;
  } catch {
    return 0;
  }
}

const label = (n: NoteRecord) =>
  n.wallMs !== null ? new Date(n.wallMs).toLocaleString() : `unknown time · note ${n.fileId}`;

function wavUrl(n: NoteRecord): string {
  const d = decodeE32(n.bytes);
  return URL.createObjectURL(new Blob([wavBytes(d.samples, d.sampleRate) as BlobPart], { type: "audio/wav" }));
}

export async function mountView(root: HTMLElement, deps: ViewDeps): Promise<void> {
  const status = el("p", { id: "status", textContent: "Flick the device switch on-off (or hold its button 1.5 s), then tap Connect & sync." });
  const progress = el("progress", { id: "progress", max: 1, value: 0 });
  const del = el("input", { id: "delete-after-sync", type: "checkbox",
    checked: await deps.db.getSetting("deleteAfterSync", true) });
  const button = el("button", { id: "sync", textContent: "Connect & sync" });
  const notes = el("ul", { id: "notes" });
  const player = el("audio", { id: "player", controls: true });

  async function renderNotes(): Promise<void> {
    notes.replaceChildren(...(await deps.db.listNotes()).map((n) => {
      const play = el("button", { className: "play", textContent: "Play" });
      play.onclick = () => {
        if (player.src) URL.revokeObjectURL(player.src);
        player.src = wavUrl(n);
        player.play().catch(() => { /* autoplay may be refused; the controls still work */ });
      };
      const save = el("button", { className: "save", textContent: "Save WAV" });
      save.onclick = () => {
        const a = el("a", { href: wavUrl(n), download: `espeak32-${n.key.replaceAll(":", "_")}.wav` });
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
      };
      return el("li", {}, el("span", { className: "when", textContent: label(n) }), " ",
        el("span", { className: "dur", textContent: `${durationS(n.bytes).toFixed(1)} s` }), " ", play, " ", save);
    }));
  }

  del.onchange = () => void deps.db.setSetting("deleteAfterSync", del.checked);
  button.onclick = async () => {
    button.disabled = true;
    status.textContent = "Connecting…";
    void requestPersistence(); // before notes are deleted from the device, ask Chrome to keep our storage
    let first = true;
    try {
      const rep = await syncAll(() => {
        const t = deps.connect(!first);
        first = false;
        return t;
      }, deps.db, { deleteAfterSync: del.checked, nowMs: () => Date.now() }, {
        onStatus: (s) => { status.textContent = s; },
        onProgress: (_k, got, total) => { progress.max = total; progress.value = got; },
        onNote: () => void renderNotes(),
      });
      const skipped = rep.skipped.map(([id, why]) => `note ${id}: ${why}`).join("; ");
      status.textContent = `Synced ${rep.fetched.length} new note(s)` + (skipped ? `. Skipped ${skipped}.` : ".");
      if (del.checked && (await requestPersistence()) === "best-effort") {
        status.textContent += " Warning: Chrome may evict stored notes when the phone is low on space; save important ones as WAV.";
      }
    } catch (e) {
      status.textContent = `Sync failed: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      button.disabled = false;
      await renderNotes();
    }
  };

  root.replaceChildren(
    el("h1", { textContent: "ESPeak32" }),
    el("p", { className: "privacy", textContent:
      "Audio stays on this phone until M3; never dictate identifiable patient information." }),
    button, " ", el("label", {}, del, " Delete from device after sync"), status, progress,
    el("h2", { textContent: "Notes" }), notes, player,
  );
  await renderNotes();
}

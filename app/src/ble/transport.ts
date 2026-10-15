/** A connected link to the device. CTRL and DATA notifications share one ATT bearer, so they come through one
 *  ordered event queue: TRANSFER_DONE always follows the transfer's last DATA chunk. */
export class LinkLost extends Error {}
export class TimeoutError extends Error {}

export type LinkEvent = ["ctrl" | "data", Uint8Array];

export interface Transport {
  readInfo(): Promise<Uint8Array>;
  writeCtrl(b: Uint8Array): Promise<void>;
  /** Rejects with TimeoutError after `timeoutMs`, or LinkLost once the link is gone and the queue is drained. */
  nextEvent(timeoutMs: number): Promise<LinkEvent>;
  close(): Promise<void>;
}

import { describe, expect, it } from "vitest";

import {
  ReconnectingPort,
  type BridgeEvent,
  type BridgePort,
} from "./reconnecting-port";

class FakeEvent<T> implements BridgeEvent<T> {
  listeners: Array<(message: T) => void> = [];

  addListener(listener: (message: T) => void): void {
    this.listeners.push(listener);
  }

  emit(message: T): void {
    for (const listener of this.listeners) listener(message);
  }
}

class FakePort implements BridgePort {
  readonly messages: unknown[] = [];
  readonly onMessage = new FakeEvent<unknown>();
  readonly onDisconnect = new FakeEvent<void>();
  disconnected = false;

  postMessage(message: unknown): void {
    if (this.disconnected) throw new Error("disconnected port");
    this.messages.push(message);
  }
}

describe("ReconnectingPort", () => {
  it("reconnects after worker suspension and forwards later messages", () => {
    const first = new FakePort();
    const second = new FakePort();
    const ports = [first, second];
    const scheduled: Array<() => void> = [];
    const received: unknown[] = [];
    const bridge = new ReconnectingPort(
      () => ports.shift()!,
      (message) => received.push(message),
      (callback) => scheduled.push(callback),
    );

    bridge.start();
    first.disconnected = true;
    first.onDisconnect.emit(undefined);
    expect(scheduled).toHaveLength(1);

    scheduled.shift()!();
    bridge.postMessage({ type: "GET_STATUS" });
    second.onMessage.emit({ type: "STATUS_CHANGED" });

    expect(second.messages).toEqual([{ type: "GET_STATUS" }]);
    expect(received).toEqual([{ type: "STATUS_CHANGED" }]);
  });

  it("retries immediately when a stale port throws on post", () => {
    const first = new FakePort();
    first.disconnected = true;
    const second = new FakePort();
    const ports = [first, second];
    const bridge = new ReconnectingPort(
      () => ports.shift()!,
      () => undefined,
      () => undefined,
    );

    bridge.start();
    bridge.postMessage({ type: "GET_STATUS" });

    expect(second.messages).toEqual([{ type: "GET_STATUS" }]);
  });
});

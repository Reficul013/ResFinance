export interface BridgeEvent<T> {
  addListener(listener: (message: T) => void): void;
}

export interface BridgePort {
  postMessage(message: unknown): void;
  onMessage: BridgeEvent<unknown>;
  onDisconnect: BridgeEvent<void>;
}

type ConnectPort = () => BridgePort;
type ScheduleReconnect = (callback: () => void) => void;

export class ReconnectingPort {
  readonly #connectPort: ConnectPort;
  readonly #onMessage: (message: unknown) => void;
  readonly #scheduleReconnect: ScheduleReconnect;
  #port: BridgePort | null = null;
  #reconnectScheduled = false;

  constructor(
    connectPort: ConnectPort,
    onMessage: (message: unknown) => void,
    scheduleReconnect: ScheduleReconnect,
  ) {
    this.#connectPort = connectPort;
    this.#onMessage = onMessage;
    this.#scheduleReconnect = scheduleReconnect;
  }

  start(): void {
    this.#ensurePort();
  }

  postMessage(message: unknown): void {
    const current = this.#ensurePort();
    try {
      current.postMessage(message);
    } catch {
      if (this.#port === current) this.#port = null;
      this.#ensurePort().postMessage(message);
    }
  }

  #ensurePort(): BridgePort {
    if (this.#port !== null) return this.#port;
    const next = this.#connectPort();
    this.#port = next;
    next.onMessage.addListener(this.#onMessage);
    next.onDisconnect.addListener(() => {
      if (this.#port !== next) return;
      this.#port = null;
      this.#queueReconnect();
    });
    return next;
  }

  #queueReconnect(): void {
    if (this.#reconnectScheduled) return;
    this.#reconnectScheduled = true;
    this.#scheduleReconnect(() => {
      this.#reconnectScheduled = false;
      try {
        this.#ensurePort();
      } catch {
        this.#queueReconnect();
      }
    });
  }
}

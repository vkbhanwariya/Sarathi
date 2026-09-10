import type { ApplicationViewState, StateEnvelope } from "./types";

export class MukhaApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "MukhaApiError";
  }
}

async function parseEnvelope(response: Response): Promise<StateEnvelope> {
  let payload: StateEnvelope;
  try {
    payload = (await response.json()) as StateEnvelope;
  } catch {
    throw new MukhaApiError("Mukha returned an invalid JSON response.", response.status);
  }

  if (!response.ok || !payload.ok) {
    throw new MukhaApiError(payload.error || `Mukha request failed (${response.status}).`, response.status);
  }
  return payload;
}

export async function fetchState(signal?: AbortSignal): Promise<ApplicationViewState> {
  const response = await fetch("/api/state", {
    method: "GET",
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" },
  });
  const payload = await parseEnvelope(response);
  if (!payload.state) {
    throw new MukhaApiError("Mukha state response did not include state.", response.status);
  }
  return payload.state;
}

export interface StateStream {
  close(): void;
}

export function subscribeState(
  onState: (state: ApplicationViewState) => void,
  onConnection: (connected: boolean) => void,
): StateStream | null {
  if (typeof EventSource === "undefined") return null;

  const source = new EventSource("/api/events");
  source.onopen = () => onConnection(true);
  source.addEventListener("state", (event) => {
    try {
      const payload = JSON.parse((event as MessageEvent<string>).data) as StateEnvelope;
      if (payload.ok && payload.state) onState(payload.state);
    } catch {
      // A malformed event is ignored; the next valid state event will reconcile the view.
    }
  });
  source.onerror = () => onConnection(false);

  return {
    close() {
      source.close();
      onConnection(false);
    },
  };
}

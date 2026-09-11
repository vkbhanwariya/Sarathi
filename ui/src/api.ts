import type {
  ApplicationViewState,
  InputSelectionView,
  InspectorViewState,
  PlanPreview,
  PreflightView,
  RunRequest,
  RunSummaryView,
  StateEnvelope,
  TerminalRunHistoryView,
} from "./types";

export class MukhaApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "MukhaApiError";
  }
}

interface ApiEnvelope {
  ok: boolean;
  error?: string;
}

async function parseJson<T extends ApiEnvelope>(response: Response): Promise<T> {
  let payload: T;
  try {
    payload = (await response.json()) as T;
  } catch {
    throw new MukhaApiError("Mukha returned an invalid JSON response.", response.status);
  }
  if (!response.ok || !payload.ok) {
    throw new MukhaApiError(payload.error || `Mukha request failed (${response.status}).`, response.status);
  }
  return payload;
}

async function getJson<T extends ApiEnvelope>(url: string, signal?: AbortSignal): Promise<T> {
  return parseJson<T>(
    await fetch(url, {
      method: "GET",
      cache: "no-store",
      signal,
      headers: { Accept: "application/json" },
    }),
  );
}

async function postJson<T extends ApiEnvelope>(url: string, body: unknown = {}): Promise<T> {
  return parseJson<T>(
    await fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function fetchState(signal?: AbortSignal): Promise<ApplicationViewState> {
  const payload = await getJson<StateEnvelope>("/api/state", signal);
  if (!payload.state) throw new MukhaApiError("Mukha state response did not include state.");
  return payload.state;
}

export async function browseFiles(): Promise<readonly string[]> {
  const payload = await postJson<ApiEnvelope & { paths?: readonly string[] }>("/api/browse/files");
  return payload.paths ?? [];
}

export async function browseFolder(): Promise<readonly string[]> {
  const payload = await postJson<ApiEnvelope & { paths?: readonly string[] }>("/api/browse/folder");
  return payload.paths ?? [];
}

export async function intakePaths(
  paths: readonly string[],
  recursive: boolean,
): Promise<{ input_selection: InputSelectionView; preflight: PreflightView }> {
  const payload = await postJson<
    ApiEnvelope & { input_selection?: InputSelectionView; preflight?: PreflightView }
  >("/api/intake", { paths, recursive });
  if (!payload.input_selection || !payload.preflight) {
    throw new MukhaApiError("Mukha intake response was incomplete.");
  }
  return { input_selection: payload.input_selection, preflight: payload.preflight };
}

export async function previewPlan(request: RunRequest): Promise<PlanPreview> {
  const payload = await postJson<ApiEnvelope & Partial<PlanPreview>>("/api/plan/preview", request);
  if (!payload.stages || !payload.devices || typeof payload.document_count !== "number") {
    throw new MukhaApiError("Mukha plan preview response was incomplete.");
  }
  return { stages: payload.stages, devices: payload.devices, document_count: payload.document_count };
}

export async function startRun(request: RunRequest): Promise<string> {
  const payload = await postJson<ApiEnvelope & { run_id?: string }>("/api/runs", request);
  if (!payload.run_id) throw new MukhaApiError("Mukha did not return a run identifier.");
  return payload.run_id;
}

export async function cancelRun(runId: string): Promise<boolean> {
  const payload = await postJson<ApiEnvelope & { cancelled?: boolean }>(
    `/api/runs/${encodeURIComponent(runId)}/cancel`,
  );
  return Boolean(payload.cancelled);
}

export async function revealRun(runId: string): Promise<boolean> {
  const payload = await postJson<ApiEnvelope & { revealed?: boolean }>(
    `/api/runs/${encodeURIComponent(runId)}/reveal`,
  );
  return Boolean(payload.revealed);
}

export async function fetchHistory(limit = 30): Promise<readonly TerminalRunHistoryView[]> {
  const payload = await getJson<ApiEnvelope & { history?: readonly TerminalRunHistoryView[] }>(
    `/api/history?limit=${encodeURIComponent(String(limit))}`,
  );
  return payload.history ?? [];
}

export async function fetchRunSummary(runId: string): Promise<RunSummaryView> {
  const payload = await getJson<ApiEnvelope & { summary?: RunSummaryView }>(
    `/api/runs/${encodeURIComponent(runId)}/summary`,
  );
  if (!payload.summary) throw new MukhaApiError(`Run summary is unavailable for ${runId}.`);
  return payload.summary;
}

export async function fetchInspector(runId: string): Promise<InspectorViewState> {
  const payload = await getJson<ApiEnvelope & { inspector?: InspectorViewState }>(
    `/api/runs/${encodeURIComponent(runId)}/inspector`,
  );
  if (!payload.inspector) throw new MukhaApiError(`Inspector data is unavailable for ${runId}.`);
  return payload.inspector;
}

export async function clearHistory(): Promise<boolean> {
  const payload = await postJson<ApiEnvelope & { cleared?: boolean }>("/api/history/clear");
  return Boolean(payload.cleared);
}

export async function clearCache(): Promise<number> {
  const payload = await postJson<ApiEnvelope & { cleared_entries?: number }>("/api/cache/clear");
  return payload.cleared_entries ?? 0;
}

export async function submitReview(
  runId: string,
  itemId: string,
  attemptId: string,
  action: "accept" | "unresolved",
): Promise<void> {
  await postJson<ApiEnvelope>("/api/review", {
    run_id: runId,
    item_id: itemId,
    attempt_id: attemptId,
    action,
  });
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
      // The next valid event or polling refresh reconciles malformed event data.
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

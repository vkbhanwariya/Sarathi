export type ProgressKind = "known" | "indeterminate" | "unavailable";

export interface ProgressState {
  kind: ProgressKind;
  completed: number;
  total: number;
  percentage: number | null;
}

export interface InputItemView {
  input_id: string;
  display_name: string;
  size_bytes: number;
  media_type: string | null;
  is_eligible: boolean;
  issue_reason: string | null;
  source_path: string | null;
}

export interface InputSelectionView {
  total_files: number;
  total_size_bytes: number;
  is_grouped: boolean;
  items: readonly InputItemView[];
}

export interface AvailableActionView {
  action_id: string;
  label: string;
  is_enabled: boolean;
  disabled_reason: string | null;
  description: string;
}

export interface RunViewState {
  run_id: string;
  status: string;
  elapsed_ns: number;
  terminal_files: number;
  total_files: number;
  progress: ProgressState | null;
}

export interface ReviewItemView {
  item_id: string;
  attempt_id: string;
  file_display_name: string;
  stage: string;
  issue_reason: string;
  page_number: number | null;
  confidence: number | null;
  status: string;
}

export interface ArtifactOutcomeView {
  artifact_id: string;
  role: string;
  display_name: string;
  size_bytes: number | null;
}

export interface RunSummaryView {
  run_id: string;
  status: string;
  wall_time_ns: number;
  total_inputs: number;
  successful_files: number | null;
  warning_files: number | null;
  failed_files: number | null;
  artifacts: readonly ArtifactOutcomeView[];
  warnings: readonly string[];
  failures: readonly string[];
}

export interface InspectorViewState {
  run_id: string;
  status: string;
  elapsed_ns: number;
}

export interface StartupViewState {
  is_initializing: boolean;
  current_stage: string;
  elapsed_ns: number;
  is_failed: boolean;
  failure_message: string | null;
}

export interface ApplicationViewState {
  schema_version: number;
  state_revision: number;
  current_screen: string;
  requirement: string;
  policy_label: string;
  input_selection: InputSelectionView;
  available_actions: readonly AvailableActionView[];
  active_run: RunViewState | null;
  review_queue: readonly ReviewItemView[];
  terminal_summary: RunSummaryView | null;
  inspector: InspectorViewState | null;
  startup: StartupViewState | null;
}

export interface StateEnvelope {
  ok: boolean;
  state?: ApplicationViewState;
  state_revision?: number;
  error?: string;
}

export type ProgressKind = "known" | "indeterminate" | "unavailable";

export interface ProgressState {
  kind: ProgressKind;
  completed: number;
  total: number;
  percentage: number | null;
}

export interface InputGroupView {
  format_name: string;
  file_count: number;
  total_size_bytes: number;
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
  groups: readonly InputGroupView[];
  items: readonly InputItemView[];
}

export interface PreflightView {
  eligible_count: number;
  issue_count: number;
  issues: readonly (readonly [string, string])[];
}

export interface ActionParameterView {
  parameter_id: string;
  display_name: string;
  kind: "select" | "toggle" | "text" | string;
  default_value: unknown;
  options: readonly (readonly [string, string])[];
  is_required: boolean;
  description: string;
}

export interface AvailableActionView {
  action_id: string;
  label: string;
  is_enabled: boolean;
  disabled_reason: string | null;
  description: string;
  parameters: readonly ActionParameterView[];
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
  source_text: string;
  output_text: string;
  issue_reason: string;
  page_number: number | null;
  confidence: number | null;
  device_type: string;
  elapsed_ns: number;
  status: string;
  draft_proposal: string | null;
  available_actions: readonly string[];
}

export interface ArtifactOutcomeView {
  artifact_id: string;
  role: string;
  display_name: string;
  size_bytes: number | null;
  sha256_hex: string | null;
}

export interface RunSummaryView {
  run_id: string;
  status: string;
  wall_time_ns: number;
  total_inputs: number;
  successful_files: number | null;
  warning_files: number | null;
  failed_files: number | null;
  quarantined_count: number | null;
  retry_count: number | null;
  avg_duration_per_input_ns: number | null;
  avg_confidence: number | null;
  accuracy: number | null;
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
  preflight: PreflightView | null;
  available_actions: readonly AvailableActionView[];
  active_run: RunViewState | null;
  review_queue: readonly ReviewItemView[];
  terminal_summary: RunSummaryView | null;
  inspector: InspectorViewState | null;
  startup: StartupViewState | null;
}

export interface RunRequest {
  paths: readonly string[];
  requirement: string;
  profile: string;
  recursive: boolean;
  custom_options: Readonly<Record<string, unknown>>;
}

export interface PlanStage {
  name: string;
}

export interface PlanDevice {
  device_type: string;
  is_available: boolean;
}

export interface PlanPreview {
  stages: readonly PlanStage[];
  devices: readonly PlanDevice[];
  document_count: number;
}

export interface StateEnvelope {
  ok: boolean;
  state?: ApplicationViewState;
  state_revision?: number;
  error?: string;
}

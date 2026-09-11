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

export interface OperationView {
  operation_name: string;
  stage: string;
  device_type: string;
  elapsed_ns: number;
  is_long_running: boolean;
  last_activity: string | null;
  progress: ProgressState | null;
}

export interface WorkerPageView {
  worker_id: string;
  file_display_name: string;
  page_number: number | null;
  stage: string;
  device_type: string;
  elapsed_ns: number;
  idle_ns: number;
  status: string;
}

export interface FileRunView {
  input_id: string;
  display_name: string;
  ordinal: number;
  status: string;
  elapsed_ns: number | null;
  current_stage: string;
  warning_count: number;
  error_message: string | null;
}

export interface DeviceProgressView {
  device_type: string;
  execution_count: number;
  total_duration_ns: number;
  avg_duration_ns: number | null;
  avg_confidence: number | null;
}

export interface RunViewState {
  run_id: string;
  status: string;
  elapsed_ns: number;
  terminal_files: number;
  total_files: number;
  current_focus: OperationView | null;
  files: readonly FileRunView[];
  active_workers: readonly WorkerPageView[];
  device_progress: readonly DeviceProgressView[];
  long_running: readonly OperationView[];
  progress: ProgressState | null;
}

export interface StageTimingView {
  stage_name: string;
  duration_ns: number;
  call_count: number;
}

export interface DeviceSummaryView {
  device_type: string;
  execution_count: number;
  attempts: number;
  avg_duration_ns: number | null;
  p95_duration_ns: number | null;
  avg_confidence: number | null;
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
  stage_timings: readonly StageTimingView[];
  device_summaries: readonly DeviceSummaryView[];
  artifacts: readonly ArtifactOutcomeView[];
  warnings: readonly string[];
  failures: readonly string[];
}

export interface WorkerPerformanceView {
  worker_id: string;
  device_type: string;
  device_id: string;
  tasks_completed: number;
  pages_completed: number;
  total_duration_ms: number;
  avg_duration_ms: number;
  throughput_per_sec: number;
  status: string;
}

export interface PageConfidenceView {
  file_display_name: string;
  page_number: number;
  confidence_score: number | null;
  region_count: number;
  min_confidence: number | null;
  max_confidence: number | null;
  review_recommended: boolean;
}

export interface RegionConfidenceView {
  region_id: string;
  file_display_name: string;
  page_number: number;
  confidence_score: number | null;
  region_type: string;
  method: string;
  review_recommended: boolean;
  original_confidence: number | null;
  confidence_gain: number | null;
  raw_confidence_score_delta: number | null;
  fallback_engine: string | null;
}

export interface FallbackImprovementView {
  region_id: string;
  file_display_name: string;
  page_number: number;
  original_confidence: number;
  improved_confidence: number;
  confidence_gain: number;
  fallback_engine: string;
  raw_confidence_score_delta: number | null;
}

export interface ActivityLogView {
  timestamp: string;
  severity: string;
  component: string;
  message: string;
}

export interface InspectorViewState {
  run_id: string;
  status: string;
  elapsed_ns: number;
  activity_logs: readonly ActivityLogView[];
  stage_timings: readonly StageTimingView[];
  device_summaries: readonly DeviceSummaryView[];
  confidence_distribution: readonly (readonly [string, number])[];
  system_facts: readonly (readonly [string, string])[];
  worker_performance: readonly WorkerPerformanceView[];
  page_confidence: readonly PageConfidenceView[];
  region_confidence: readonly RegionConfidenceView[];
  fallback_improvements: readonly FallbackImprovementView[];
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

export interface TerminalRunHistoryView {
  run_id: string;
  request_id: string;
  requirement: string;
  profile: string;
  status: "completed" | "failed" | "cancelled" | string;
  start_time_utc: string;
  completed_at_utc: string;
  duration_ms: number;
  artifact_count: number;
  warning_count: number;
  has_masked_identity: boolean;
  output_dir: string | null;
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

export interface DocumentPreviewTable {
  headers?: readonly string[];
  rows?: readonly (readonly string[])[];
}

export interface DocumentPreviewData {
  ok: boolean;
  type?: "pdf" | "word" | "text" | "tabular" | "image" | "binary" | string;
  name?: string;
  size?: number;
  raw_path?: string;
  error?: string;
  current_page?: number;
  page_count?: number;
  page_data_url?: string;
  page_text?: string;
  total_paragraphs?: number;
  paragraphs?: readonly string[];
  tables?: readonly DocumentPreviewTable[];
  content?: string;
  truncated?: boolean;
  headers?: readonly string[];
  rows?: readonly (readonly string[])[];
  data_url?: string;
}

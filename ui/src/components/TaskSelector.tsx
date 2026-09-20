import { useEffect, useState } from "preact/hooks";
import { ActionParameter } from "./Common";
import type { AvailableActionView } from "../types";
import {
  PRIMARY_TASKS,
  CLOUD_OCR_PROVIDERS,
  TRANSLATION_ENGINES,
  MODULES,
  type PrimaryTaskId,
  type ModuleId,
} from "../workflow/taskCatalog";

export interface TaskSelectorProps {
  primaryTask: PrimaryTaskId | null;
  currentSubtask: string | undefined;
  subtaskByPrimary: Record<PrimaryTaskId, string>;
  availableActions: readonly AvailableActionView[];
  cloudOcrProvider: string;
  transDirection: string;
  statutoryEnabled: boolean;
  convertLegacyFonts: boolean;
  layoutAnalysis: boolean;
  preserveLayout: boolean;
  sourceFont: string;
  skipHeaderFooter: boolean;
  ocrCustomParams: Record<string, unknown>;
  onSelectPrimaryTask: (task: PrimaryTaskId | null) => void;
  onSelectSubtask: (primary: PrimaryTaskId, subtask: string) => void;
  onSetCloudOcrProvider: (provider: string) => void;
  onSetTransDirection: (direction: string) => void;
  onSetStatutoryEnabled: (enabled: boolean) => void;
  onSetConvertLegacyFonts: (enabled: boolean) => void;
  onSetLayoutAnalysis: (enabled: boolean) => void;
  onSetPreserveLayout: (enabled: boolean) => void;
  onSetSourceFont: (font: string) => void;
  onSetSkipHeaderFooter: (enabled: boolean) => void;
  onSetOcrCustomParam: (key: string, value: unknown) => void;
}

export function TaskSelector({
  primaryTask,
  currentSubtask,
  subtaskByPrimary,
  availableActions,
  cloudOcrProvider,
  transDirection,
  statutoryEnabled,
  convertLegacyFonts,
  layoutAnalysis,
  preserveLayout,
  sourceFont,
  skipHeaderFooter,
  ocrCustomParams,
  onSelectPrimaryTask,
  onSelectSubtask,
  onSetCloudOcrProvider,
  onSetTransDirection,
  onSetStatutoryEnabled,
  onSetConvertLegacyFonts,
  onSetLayoutAnalysis,
  onSetPreserveLayout,
  onSetSourceFont,
  onSetSkipHeaderFooter,
  onSetOcrCustomParam,
}: TaskSelectorProps) {
  const [activeModule, setActiveModule] = useState<ModuleId | "all">("documents_handling");
  const [viewMode, setViewMode] = useState<"workflows" | "custom">("workflows");

  useEffect(() => {
    if (primaryTask) {
      const task = PRIMARY_TASKS.find((t) => t.id === primaryTask);
      if (task && task.moduleId !== activeModule) {
        setActiveModule(task.moduleId);
      }
    }
  }, [primaryTask]);

  const ocrAction = availableActions.find((a) => a.action_id === "ocr");

  const filteredTasks = PRIMARY_TASKS.filter((task) => {
    if (activeModule === "all") return true;
    return task.moduleId === activeModule;
  });

  const renderTaskIcon = (id: PrimaryTaskId) => {
    switch (id) {
      case "documents_extraction":
        return (
          <div class="task-icon-box task-icon-box--indigo">
            <svg class="task-svg-icon" width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.8"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
          </div>
        );
      case "font_conversion":
        return (
          <div class="task-icon-box task-icon-box--blue">
            <svg class="task-svg-icon" width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M3 5h12M9 5v14m4-7h8m-4-7v14" />
            </svg>
          </div>
        );
      case "translation":
        return (
          <div class="task-icon-box task-icon-box--cyan">
            <svg class="task-svg-icon" width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.8"
                d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"
              />
            </svg>
          </div>
        );
      case "bank_consolidation":
        return (
          <div class="task-icon-box task-icon-box--emerald">
            <svg class="task-svg-icon" width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.8"
                d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"
              />
            </svg>
          </div>
        );
    }
  };

  return (
    <div class="tasks-modern-container">
      {/* Top Module & Mode Navigation Toolbar */}
      <div class="tasks-toolbar">
        <div class="module-segmented-control" role="tablist" aria-label="Operational Modules">
          {MODULES.map((mod) => (
            <button
              key={mod.id}
              id={`btn-module-${mod.id.replace(/_/g, "-")}`}
              class={`module-pill-btn ${activeModule === mod.id ? "active" : ""}`}
              onClick={() => setActiveModule(mod.id)}
              type="button"
            >
              <span class="module-btn-icon">
                {mod.id === "documents_handling" ? (
                  <svg class="task-svg-icon" width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                  </svg>
                ) : (
                  <svg class="task-svg-icon" width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
                  </svg>
                )}
              </span>
              <span>{mod.id === "bank_statement_analysis" ? "Bank Statements" : "Documents Studio"}</span>
            </button>
          ))}
        </div>

        <div class="mode-toggle-pill-group">
          <button
            id="btn-mode-workflows"
            class={`mode-pill-btn ${viewMode === "workflows" ? "active" : ""}`}
            onClick={() => setViewMode("workflows")}
            type="button"
            title="Standard streamlined office workflows"
          >
            <span class="mode-bolt-icon">⚡</span>
            <span>Workflows</span>
          </button>
          <button
            id="btn-mode-custom"
            class={`mode-pill-btn ${viewMode === "custom" ? "active" : ""}`}
            onClick={() => {
              setViewMode("custom");
              if (!primaryTask) {
                onSelectPrimaryTask("documents_extraction");
                onSelectSubtask("documents_extraction", "native");
              }
            }}
            type="button"
            title="Advanced step-by-step modular pipeline builder"
          >
            <span>⚙️</span>
            <span>Custom Pipeline</span>
          </button>
        </div>
      </div>

      {viewMode === "workflows" ? (
        /* Primary Workflows Layered Deck */
        <div class={`tasks-accordion tasks-deck ${primaryTask ? "in-deep-dive" : "in-deck-view"}`} role="tablist" aria-label="Primary Tasks">
        {primaryTask && (
          <div class="deck-layer-topbar">
            <button
              id="btn-back-to-deck"
              class="deck-back-btn"
              type="button"
              onClick={() => onSelectPrimaryTask(null)}
              title="Return to card deck"
            >
              <span class="back-arrow">←</span>
              <span>All Workflows</span>
            </button>
            <div class="deck-layer-indicator">
              <span class="layer-dot" />
              <span>Deep Dive: {PRIMARY_TASKS.find((t) => t.id === primaryTask)?.badge || "Options"}</span>
            </div>
          </div>
        )}
        {filteredTasks.map((task) => {
          const isSelected = primaryTask === task.id;
          return (
            <div
              key={task.id}
              class={`accordion-item ${isSelected ? "expanded active-layer" : "collapsed stacked-layer"}`}
              data-task={task.id}
              data-module={task.moduleId}
            >
              <button
                id={`btn-task-${task.id.replace(/_/g, "-")}`}
                data-task={task.id}
                class={`primary-task-tab-btn accordion-header-btn ${isSelected ? "active" : ""}`}
                role="tab"
                aria-selected={isSelected}
                aria-expanded={isSelected}
                type="button"
                onClick={() => onSelectPrimaryTask(isSelected ? null : task.id)}
              >
                <div class="accordion-header-left">
                  {renderTaskIcon(task.id)}
                  <div class="primary-task-info">
                    <div class="task-title-row">
                      <h3 class="primary-task-label">{task.label}</h3>
                      {task.badge ? (
                        <span class={`task-tag-badge task-tag-badge--${task.id}`}>{task.badge}</span>
                      ) : null}
                    </div>
                    <p class="primary-task-desc">{task.description}</p>
                  </div>
                </div>
                <div class="accordion-header-right">
                  <span class="accordion-badge-pill">
                    <span>{isSelected ? "Active" : "Select"}</span>
                    <span class={`accordion-chevron ${isSelected ? "open" : ""}`} aria-hidden="true">
                      ▾
                    </span>
                  </span>
                </div>
              </button>

              {/* Progressive Subtasks and Controls */}
              {isSelected && (
                <div class="accordion-body">
                  {/* Task 1: Scan to Word & Document Extraction */}
                  {task.id === "documents_extraction" && (
                    <div class="subtasks-container">
                      {/* Executive Office Deliverable Banner & Quick Intent Pills */}
                      <div class="workflow-deliverable-banner">
                        <div class="deliverable-banner-left">
                          <span class="deliverable-tag">OFFICE DELIVERABLE</span>
                          <strong class="deliverable-title">Editable Word Document (.docx) &amp; Excel (.xlsx)</strong>
                          <span class="deliverable-desc">
                            Preserves paragraph margins, column geometry, and table structures with clean Unicode Devanagari.
                          </span>
                        </div>
                        <div class="deliverable-quick-pills" role="group" aria-label="Quick Office Intent Actions">
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "instant_ocr" && convertLegacyFonts ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("documents_extraction", "instant_ocr");
                              onSetConvertLegacyFonts(true);
                            }}
                            title="RapidOCR on Intel Arc iGPU with clean Unicode Hindi Word output"
                          >
                            <span class="intent-pill-icon">🇮🇳</span>
                            <span>Hindi Word (Clean Unicode)</span>
                          </button>
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "accurate_ocr" && preserveLayout ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("documents_extraction", "accurate_ocr");
                              onSetPreserveLayout(true);
                            }}
                            title="Deep OCR with full paragraph and table layout preservation"
                          >
                            <span class="intent-pill-icon">🌐</span>
                            <span>English Word (Translated)</span>
                          </button>
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "native" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("documents_extraction", "native");
                            }}
                            title="Direct digital text & table vector extraction (0.05s/page)"
                          >
                            <span class="intent-pill-icon">⚡</span>
                            <span>Fast / Direct Word</span>
                          </button>
                        </div>
                      </div>

                      <div class="subtasks-grid">
                        {/* 1.1 Native Extraction */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "read_native");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "native";
                          return (
                            <div
                              key="native"
                              id="subtask-native"
                              data-subtask="native"
                              data-req="read_native"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("documents_extraction", "native")}
                              title={isEnabled ? "Direct digital extraction from PDF, DOCX, XLSX, XLS, CSV." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Native Digital & Tables</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>DIGITAL</span>
                              </div>
                              <p class="action-card-desc">
                                Direct digital extraction from PDF, DOCX, XLSX, XLS, CSV. Extracts tables and text without OCR overhead.
                              </p>
                              {isSel && (
                                <div class="subtask-options-row" onClick={(e) => e.stopPropagation()}>
                                  <label class="toggle-row mini">
                                    <input
                                      id="param-convert-legacy-fonts"
                                      type="checkbox"
                                      checked={convertLegacyFonts}
                                      onChange={(e) => {
                                        onSetConvertLegacyFonts(e.currentTarget.checked);
                                        onSelectSubtask("documents_extraction", "native");
                                      }}
                                    />
                                    <span>
                                      <strong>Convert Legacy Fonts to Unicode</strong>
                                    </span>
                                  </label>
                                  <label class="toggle-row mini" title="Use Graph Neural Networks for multi-column flow, table grids, and semantic headers">
                                    <input
                                      id="param-layout-analysis"
                                      type="checkbox"
                                      checked={layoutAnalysis}
                                      onChange={(e) => {
                                        onSetLayoutAnalysis(e.currentTarget.checked);
                                        onSelectSubtask("documents_extraction", "native");
                                      }}
                                    />
                                    <span>
                                      <strong>Deep Layout Analysis (GNN)</strong>
                                    </span>
                                  </label>
                                  <label class="toggle-row mini">
                                    <input
                                      id="param-statutory"
                                      type="checkbox"
                                      checked={statutoryEnabled}
                                      onChange={(e) => {
                                        onSetStatutoryEnabled(e.currentTarget.checked);
                                        onSelectSubtask("documents_extraction", "native");
                                      }}
                                    />
                                    <span>
                                      <strong>Statutory Legal ID Detection</strong>
                                    </span>
                                  </label>
                                  <label class="toggle-row mini" title="Detect and separate running page headers and footers from continuous narrative text">
                                    <input
                                      id="param-skip-header-footer"
                                      type="checkbox"
                                      checked={skipHeaderFooter}
                                      onChange={(e) => {
                                        onSetSkipHeaderFooter(e.currentTarget.checked);
                                        onSelectSubtask("documents_extraction", "native");
                                      }}
                                    />
                                    <span>
                                      <strong>Separate Running Headers/Footers</strong>
                                    </span>
                                  </label>
                                </div>
                              )}
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">read_native</code>
                              </div>
                            </div>
                          );
                        })()}

                        {/* 1.2 Instant OCR (OpenVINO iGPU) */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "ocr");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "instant_ocr";
                          return (
                            <div
                              key="instant_ocr"
                              id="subtask-instant-ocr"
                              data-subtask="instant_ocr"
                              data-req="ocr"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("documents_extraction", "instant_ocr")}
                              title={isEnabled ? "RapidOCR inference with OpenVINO acceleration." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Scan to Word (Fast OCR)</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>INTEL iGPU</span>
                              </div>
                              <p class="action-card-desc">
                                RapidOCR OpenVINO single-pass inference on Intel Arc iGPU. Outputs fast Word documents.
                              </p>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">ocr:instant</code>
                              </div>
                            </div>
                          );
                        })()}

                        {/* 1.3 Accurate OCR */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "ocr");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "accurate_ocr";
                          return (
                            <div
                              key="accurate_ocr"
                              id="subtask-accurate-ocr"
                              data-subtask="accurate_ocr"
                              data-req="ocr"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("documents_extraction", "accurate_ocr")}
                              title={isEnabled ? "Quality-optimized OCR with full preprocessing." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Scan to Word (Accurate OCR)</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>ACCURATE</span>
                              </div>
                              <p class="action-card-desc">
                                Quality-optimized OCR with CLAHE contrast enhancement, deskew, and selective weak-crop retry.
                              </p>
                              {isSel && (
                                <div class="subtask-options-row" onClick={(e) => e.stopPropagation()}>
                                  <label class="toggle-row mini">
                                    <input
                                      id="param-preserve-layout"
                                      type="checkbox"
                                      checked={preserveLayout}
                                      onChange={(e) => {
                                        onSetPreserveLayout(e.currentTarget.checked);
                                        onSelectSubtask("documents_extraction", "accurate_ocr");
                                      }}
                                    />
                                    <span>
                                      <strong>Preserve Layout & Margin Geometry</strong>
                                    </span>
                                  </label>
                                  <label class="toggle-row mini" title="Detect and separate running page headers and footers">
                                    <input
                                      id="param-ocr-skip-header-footer"
                                      type="checkbox"
                                      checked={skipHeaderFooter}
                                      onChange={(e) => {
                                        onSetSkipHeaderFooter(e.currentTarget.checked);
                                        onSelectSubtask("documents_extraction", "accurate_ocr");
                                      }}
                                    />
                                    <span>
                                      <strong>Separate Running Headers/Footers</strong>
                                    </span>
                                  </label>
                                </div>
                              )}
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">ocr:accurate</code>
                              </div>
                            </div>
                          );
                        })()}

                        {/* 1.4 Cloud OCR */}
                        {(() => {
                          const curCloudAct = availableActions.find((a) => a.action_id === cloudOcrProvider);
                          const isEnabled = curCloudAct ? curCloudAct.is_enabled : false;
                          const isSel = currentSubtask === "cloud_ocr";
                          return (
                            <div
                              key="cloud_ocr"
                              id="subtask-cloud-ocr"
                              data-subtask="cloud_ocr"
                              data-req="cloud_ocr"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("documents_extraction", "cloud_ocr")}
                              title={isEnabled ? "External cloud multimodal document recognition." : (curCloudAct?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Cloud Document AI</h4>
                                <span class={`action-tag action-tag--cloud ${isSel ? "active" : ""}`}>CLOUD</span>
                              </div>
                              <p class="action-card-desc">
                                Multimodal cloud document recognition (Gemini / Mistral / Azure) with fail-closed privacy.
                              </p>
                              <div class="cloud-provider-chips" onClick={(e) => e.stopPropagation()}>
                                {CLOUD_OCR_PROVIDERS.map((cp) => {
                                  const act = availableActions.find((a) => a.action_id === cp.id);
                                  const isChipAvail = act ? act.is_enabled : false;
                                  const isChipActive = cloudOcrProvider === cp.id;
                                  return (
                                    <button
                                      key={cp.id}
                                      id={`chip-${cp.id.replace(/_/g, "-")}`}
                                      class={`cloud-chip ${isChipActive ? "active" : ""} ${!isChipAvail ? "disabled" : ""}`}
                                      disabled={!isChipAvail}
                                      title={isChipAvail ? cp.label : (act?.disabled_reason || "Unavailable")}
                                      type="button"
                                      onClick={() => {
                                        onSetCloudOcrProvider(cp.id);
                                        onSelectSubtask("documents_extraction", "cloud_ocr");
                                      }}
                                    >
                                      {cp.label}
                                    </button>
                                  );
                                })}
                              </div>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">{cloudOcrProvider}</code>
                              </div>
                            </div>
                          );
                        })()}

                        {/* 1.5 Custom OCR */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "ocr");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "custom_ocr";
                          return (
                            <div
                              key="custom_ocr"
                              id="subtask-custom-ocr"
                              data-subtask="custom_ocr"
                              data-req="ocr"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("documents_extraction", "custom_ocr")}
                              title={isEnabled ? "Fine-grained control over OCR parameters." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Custom Parameters</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>CUSTOM</span>
                              </div>
                              <p class="action-card-desc">
                                Granular control over detection thresholds, unclip ratios, and preprocessing toggles.
                              </p>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">ocr:custom</code>
                              </div>
                            </div>
                          );
                        })()}
                      </div>

                      {/* Custom OCR Parameter Panel */}
                      {currentSubtask === "custom_ocr" && ocrAction?.parameters.length ? (
                        <div class="parameter-section">
                          <div class="parameter-header">
                            <span class="eyebrow">Parameters</span>
                            <h4>Custom OCR Tuning</h4>
                          </div>
                          <div class="parameter-list">
                            {ocrAction.parameters.map((parameter) => (
                              <ActionParameter
                                key={parameter.parameter_id}
                                parameter={parameter}
                                value={ocrCustomParams[parameter.parameter_id] ?? parameter.default_value}
                                onChange={(value) => onSetOcrCustomParam(parameter.parameter_id, value)}
                              />
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  )}

                  {/* Task 2: Font Standardizer (Word & Excel) */}
                  {task.id === "font_conversion" && (
                    <div class="subtasks-container">
                      {/* Executive Office Deliverable Banner & Quick Intent Pills */}
                      <div class="workflow-deliverable-banner">
                        <div class="deliverable-banner-left">
                          <span class="deliverable-tag">OFFICE DELIVERABLE</span>
                          <strong class="deliverable-title">Non-destructive [Name]_Unicode.docx &amp; .xlsx</strong>
                          <span class="deliverable-desc">
                            In-place legacy Hindi font upgrade while strictly preserving Word XML geometry, Excel formulas, and numeric cells.
                          </span>
                        </div>
                        <div class="deliverable-quick-pills" role="group" aria-label="Quick Font Conversion Actions">
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "legacy_to_unicode" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("font_conversion", "legacy_to_unicode");
                            }}
                            title="Upgrade Kruti Dev / Devlys / Chanakya to clean standard Unicode"
                          >
                            <span class="intent-pill-icon">✨</span>
                            <span>To Standard Unicode</span>
                          </button>
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "unicode_to_krutidev" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("font_conversion", "unicode_to_krutidev");
                            }}
                            title="Reverse modern Unicode back to Kruti Dev 010 for typewriter submission portals"
                          >
                            <span class="intent-pill-icon">🔄</span>
                            <span>Reverse to Kruti Dev 010</span>
                          </button>
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "unicode_to_devlys" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("font_conversion", "unicode_to_devlys");
                            }}
                            title="Reverse Unicode back to Devlys 010"
                          >
                            <span class="intent-pill-icon">🔄</span>
                            <span>Reverse to Devlys 010</span>
                          </button>
                        </div>
                      </div>

                      <div class="subtasks-grid">
                        {/* 2.1 Legacy to Unicode */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "font_conversion");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "legacy_to_unicode";
                          return (
                            <div
                              key="legacy_to_unicode"
                              id="subtask-legacy-to-unicode"
                              data-subtask="legacy_to_unicode"
                              data-req="font_conversion"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("font_conversion", "legacy_to_unicode")}
                              title={isEnabled ? "Auto-detects legacy Hindi font encodings and converts to Unicode." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">To Standard Unicode (Word & Excel)</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>UNICODE</span>
                              </div>
                              <p class="action-card-desc">
                                Upgrades KrutiDev, DevLys, Chanakya, Shusha, and Shivaji in Word (.docx) and Excel (.xlsx) to clean Unicode without breaking formulas.
                              </p>
                              <div class="subtask-options-row" onClick={(e) => e.stopPropagation()}>
                                <label class="field mini" style={{ margin: 0 }}>
                                  <span style={{ fontSize: "11px" }}>Source Font Hint</span>
                                  <select
                                    id="param-source-font"
                                    value={sourceFont}
                                    onChange={(e) => onSetSourceFont(e.currentTarget.value)}
                                    style={{ padding: "3px 6px", fontSize: "11px" }}
                                  >
                                    <option value="">Auto-Detect Source Font</option>
                                    <option value="krutidev010">KrutiDev 010 / DevLys</option>
                                    <option value="chanakya010">Chanakya</option>
                                    <option value="shusha010">Shusha</option>
                                    <option value="shivaji010">Shivaji</option>
                                  </select>
                                </label>
                              </div>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">font_conversion:auto_unicode</code>
                              </div>
                            </div>
                          );
                        })()}

                        {/* 2.2 Unicode to KrutiDev */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "font_conversion");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "unicode_to_krutidev";
                          return (
                            <div
                              key="unicode_to_krutidev"
                              id="subtask-unicode-to-krutidev"
                              data-subtask="unicode_to_krutidev"
                              data-req="font_conversion"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("font_conversion", "unicode_to_krutidev")}
                              title={isEnabled ? "Reverses Unicode text into legacy KrutiDev 010." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Reverse to KrutiDev 010</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>KRUTIDEV</span>
                              </div>
                              <p class="action-card-desc">
                                Transduces Unicode text back into legacy KrutiDev 010 for older government printing portals or typewriter submissions.
                              </p>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">font_conversion:to_krutidev</code>
                              </div>
                            </div>
                          );
                        })()}

                        {/* 2.3 Unicode to DevLys */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "font_conversion");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "unicode_to_devlys";
                          return (
                            <div
                              key="unicode_to_devlys"
                              id="subtask-unicode-to-devlys"
                              data-subtask="unicode_to_devlys"
                              data-req="font_conversion"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("font_conversion", "unicode_to_devlys")}
                              title={isEnabled ? "Reverses Unicode text into legacy DevLys 010." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Reverse to DevLys 010</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>DEVLYS</span>
                              </div>
                              <p class="action-card-desc">
                                Transduces Unicode text back into legacy DevLys 010 for governmental typewriter compatibility.
                              </p>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">font_conversion:to_devlys</code>
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                    </div>
                  )}

                  {/* Task 3: Document Translation (Word, PDF & Excel) */}
                  {task.id === "translation" && (
                    <div class="subtasks-container">
                      {/* Executive Office Deliverable Banner */}
                      <div class="workflow-deliverable-banner">
                        <div class="deliverable-banner-left">
                          <span class="deliverable-tag">OFFICE DELIVERABLE</span>
                          <strong class="deliverable-title">Bilingual Word (.docx), PDF, or Excel (.xlsx)</strong>
                          <span class="deliverable-desc">
                            Neural translation with ISO 15919 phonetic proper noun protection and statutory administrative vocabulary.
                          </span>
                        </div>
                      </div>

                      {/* Direction selector */}
                      <div class="translation-direction-toolbar" role="group" aria-label="Translation Direction">
                        <button
                          id="btn-direction-auto"
                          data-dir=""
                          class={`direction-seg-btn ${transDirection === "" ? "active" : ""}`}
                          type="button"
                          onClick={() => onSetTransDirection("")}
                        >
                          ⚡ Auto-Detect Language
                        </button>
                        <button
                          id="btn-direction-hi-en"
                          data-dir="hi_en"
                          class={`direction-seg-btn ${transDirection === "hi_en" ? "active" : ""}`}
                          type="button"
                          onClick={() => onSetTransDirection("hi_en")}
                        >
                          Hindi → English
                        </button>
                        <button
                          id="btn-direction-en-hi"
                          data-dir="en_hi"
                          class={`direction-seg-btn ${transDirection === "en_hi" ? "active" : ""}`}
                          type="button"
                          onClick={() => onSetTransDirection("en_hi")}
                        >
                          English → Hindi
                        </button>
                      </div>

                      {/* Engine Choices */}
                      <div class="subtasks-grid">
                        {TRANSLATION_ENGINES.map((eng) => {
                          const act = availableActions.find((a) => a.action_id === eng.actionId);
                          const isEnabled = act ? act.is_enabled : false;
                          const isSel = currentSubtask === eng.id;
                          return (
                            <div
                              key={eng.id}
                              id={`subtask-engine-${eng.id.replace(/_/g, "-")}`}
                              data-subtask={eng.id}
                              data-req={eng.actionId}
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("translation", eng.id)}
                              title={isEnabled ? eng.desc : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">{eng.label}</h4>
                                <span class={`action-tag ${eng.isCloud ? "action-tag--cloud" : ""} ${isSel ? "active" : ""}`}>
                                  {eng.tag}
                                </span>
                              </div>
                              <p class="action-card-desc">{isEnabled ? eng.desc : (act?.disabled_reason || "Unavailable")}</p>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">{eng.code}</code>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Task 4: Bank Statement Consolidation & Audit */}
                  {task.id === "bank_consolidation" && (
                    <div class="subtasks-container">
                      {/* Executive Office Deliverable Banner & Quick Intent Pills */}
                      <div class="workflow-deliverable-banner">
                        <div class="deliverable-banner-left">
                          <span class="deliverable-tag">OFFICE DELIVERABLE</span>
                          <strong class="deliverable-title">Master Consolidated Excel (.xlsx) + 1-Page Audit Memo (.docx)</strong>
                          <span class="deliverable-desc">
                            Standardized double-entry running balance ledger with verified arithmetic, UTR repair, and forensic memo.
                          </span>
                        </div>
                        <div class="deliverable-quick-pills" role="group" aria-label="Quick Financial Reconciler Actions">
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "accurate" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("bank_consolidation", "accurate");
                            }}
                            title="Strict double-entry balance arithmetic verification and 1-page memo"
                          >
                            <span class="intent-pill-icon">🎯</span>
                            <span>Deep Verification &amp; Memo</span>
                          </button>
                          <button
                            type="button"
                            class={`intent-pill ${currentSubtask === "instant" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectSubtask("bank_consolidation", "instant");
                            }}
                            title="High-speed statement ledger parsing"
                          >
                            <span class="intent-pill-icon">⚡</span>
                            <span>Instant Consolidation</span>
                          </button>
                        </div>
                      </div>

                      {/* Bank Statement Verification Bar */}
                      <div class="bank-integrity-features-bar">
                        <span class="integrity-chip">✓ Double-Entry Verified</span>
                        <span class="integrity-chip">✓ UTR &amp; IFSC Auto-Repair</span>
                        <span class="integrity-chip">✓ Deduplication</span>
                        <span class="integrity-chip">📑 1-Page Audit Memo Included</span>
                      </div>

                      <div class="subtasks-grid">
                        {/* 4.1 Accurate Consolidation & Reconciler */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "bank_statements");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "accurate";
                          return (
                            <div
                              key="accurate"
                              id="subtask-accurate-consolidation"
                              data-subtask="accurate"
                              data-req="bank_statements"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("bank_consolidation", "accurate")}
                              title={isEnabled ? "Strict double-entry verification and UTR repair." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Accurate Reconciler & Memo</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>AUDIT-GRADE</span>
                              </div>
                              <p class="action-card-desc">
                                Strict double-entry balance arithmetic verification, UTR/IFSC auto-repair, and master Excel workbook with 1-page executive memo.
                              </p>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">bank_statements:accurate</code>
                              </div>
                            </div>
                          );
                        })()}

                        {/* 4.2 Fast Consolidation */}
                        {(() => {
                          const act = availableActions.find((a) => a.action_id === "bank_statements");
                          const isEnabled = act ? act.is_enabled : true;
                          const isSel = currentSubtask === "instant";
                          return (
                            <div
                              key="instant"
                              id="subtask-instant-consolidation"
                              data-subtask="instant"
                              data-req="bank_statements"
                              class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                              onClick={() => onSelectSubtask("bank_consolidation", "instant")}
                              title={isEnabled ? "Throughput-optimized financial statement parsing." : (act?.disabled_reason || "Unavailable")}
                            >
                              <div class="action-card-header">
                                <h4 class="action-card-name">Instant Consolidation</h4>
                                <span class={`action-tag ${isSel ? "active" : ""}`}>FAST</span>
                              </div>
                              <p class="action-card-desc">
                                Throughput-optimized parsing across financial statements using standard layout heuristics.
                              </p>
                              <div class="action-card-footer">
                                <span class={`action-dot ${isSel ? "active" : ""}`} />
                                <code class="action-code">bank_statements:instant</code>
                              </div>
                            </div>
                          );
                        })()}
                      </div>

                      {/* Planned Forensic Roadmap Indicators */}
                      <div class="roadmap-pills-row">
                        <span class="roadmap-pill" title="Planned: Monthly Average Balance and Inflow/Outflow trends">
                          📈 Cash Flow Analytics
                        </span>
                        <span class="roadmap-pill" title="Planned: Circular routing and Section 269ST cash alerts">
                          🔍 PMLA & Fraud Detection
                        </span>
                        <span class="roadmap-pill" title="Planned: Commercial counterparty exposure matrix">
                          🏷️ Counterparty Mapping
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      ) : (
        /* Custom Modular Pipeline Builder (Power User Workspace) */
        <div id="custom-mode-pipeline" class="custom-pipeline-builder">
          {/* Header Banner */}
          <div class="pipeline-builder-header">
            <div class="pipeline-header-info">
              <div class="pipeline-badge-row">
                <span class="pipeline-mode-badge">POWER USER WORKSPACE</span>
                <span class="pipeline-hw-badge">Intel Core Ultra 5 125H · Intel Arc iGPU (OpenVINO FP16)</span>
              </div>
              <h3 class="pipeline-title">Custom Modular Pipeline Builder</h3>
              <p class="pipeline-desc">
                Compose custom document-processing stages, neural routing, and hardware accelerator parameters.
              </p>
            </div>
            <div class="pipeline-status-summary">
              <div class="pipeline-flow-chips">
                <span class="flow-chip active">
                  {primaryTask === "bank_consolidation"
                    ? "Bank Statements"
                    : currentSubtask === "instant_ocr"
                    ? "RapidOCR Fast"
                    : currentSubtask === "accurate_ocr"
                    ? "RapidOCR Accurate"
                    : currentSubtask === "custom_ocr"
                    ? "Custom RapidOCR"
                    : currentSubtask === "cloud_ocr"
                    ? `Cloud OCR (${cloudOcrProvider})`
                    : "Native Vector"}
                </span>
                <span class="flow-arrow">➔</span>
                <span class={`flow-chip ${convertLegacyFonts || primaryTask === "font_conversion" ? "active" : ""}`}>
                  {convertLegacyFonts ? `Font: ${sourceFont || "Unicode"}` : primaryTask === "font_conversion" ? `Font: ${currentSubtask}` : "Font: Pass"}
                </span>
                <span class="flow-arrow">➔</span>
                <span class={`flow-chip ${primaryTask === "translation" ? "active" : ""}`}>
                  {primaryTask === "translation" ? `Trans: ${currentSubtask} (${transDirection})` : "Trans: None"}
                </span>
                <span class="flow-arrow">➔</span>
                <span class="flow-chip active">Pariksha Review</span>
              </div>
            </div>
          </div>

          {/* Stage 1: Document Extraction Engine */}
          <div class="pipeline-stage-card" id="custom-stage-extraction">
            <div class="stage-header">
              <div class="stage-number">01</div>
              <div class="stage-title-wrap">
                <h4 class="stage-title">Document Extraction Engine</h4>
                <span class="stage-subtitle">Select intake parser, OCR engine, or statement reader</span>
              </div>
            </div>
            <div class="stage-content">
              <div class="pipeline-engine-grid">
                {/* 1.1 Native */}
                <div
                  id="custom-engine-native"
                  class={`pipeline-engine-card ${primaryTask === "documents_extraction" && currentSubtask === "native" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("documents_extraction");
                    onSelectSubtask("documents_extraction", "native");
                  }}
                >
                  <div class="engine-card-header">
                    <span class="engine-card-title">PyMuPDF Native</span>
                    <span class="engine-card-badge">DIGITAL</span>
                  </div>
                  <p class="engine-card-desc">
                    Direct digital vector text and table extraction. 0.05s/page throughput with zero OCR overhead.
                  </p>
                  <code class="engine-card-code">read_native:instant</code>
                </div>

                {/* 1.2 OpenVINO RapidOCR Fast */}
                <div
                  id="custom-engine-instant-ocr"
                  class={`pipeline-engine-card ${primaryTask === "documents_extraction" && currentSubtask === "instant_ocr" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("documents_extraction");
                    onSelectSubtask("documents_extraction", "instant_ocr");
                  }}
                >
                  <div class="engine-card-header">
                    <span class="engine-card-title">RapidOCR Fast</span>
                    <span class="engine-card-badge">INTEL ARC iGPU</span>
                  </div>
                  <p class="engine-card-desc">
                    High-speed OpenVINO FP16 neural inference on Meteor Lake Xe cores. ~0.6s/page.
                  </p>
                  <code class="engine-card-code">ocr:instant</code>
                </div>

                {/* 1.3 OpenVINO RapidOCR Accurate */}
                <div
                  id="custom-engine-accurate-ocr"
                  class={`pipeline-engine-card ${primaryTask === "documents_extraction" && currentSubtask === "accurate_ocr" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("documents_extraction");
                    onSelectSubtask("documents_extraction", "accurate_ocr");
                  }}
                >
                  <div class="engine-card-header">
                    <span class="engine-card-title">RapidOCR Accurate</span>
                    <span class="engine-card-badge">LAYOUT</span>
                  </div>
                  <p class="engine-card-desc">
                    Full layout-preserving optical recognition with deep bounding box coordinates.
                  </p>
                  <code class="engine-card-code">ocr:accurate</code>
                </div>

                {/* 1.4 Custom RapidOCR */}
                <div
                  id="custom-engine-custom-ocr"
                  class={`pipeline-engine-card ${primaryTask === "documents_extraction" && currentSubtask === "custom_ocr" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("documents_extraction");
                    onSelectSubtask("documents_extraction", "custom_ocr");
                  }}
                >
                  <div class="engine-card-header">
                    <span class="engine-card-title">Custom RapidOCR</span>
                    <span class="engine-card-badge">TUNED</span>
                  </div>
                  <p class="engine-card-desc">
                    Granular threshold, unclip ratio, contrast enhancement, and neural profile overrides.
                  </p>
                  <code class="engine-card-code">ocr:custom</code>
                </div>

                {/* 1.5 Cloud OCR */}
                <div
                  id="custom-engine-cloud-ocr"
                  class={`pipeline-engine-card ${primaryTask === "documents_extraction" && currentSubtask === "cloud_ocr" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("documents_extraction");
                    onSelectSubtask("documents_extraction", "cloud_ocr");
                  }}
                >
                  <div class="engine-card-header">
                    <span class="engine-card-title">Cloud AI Vision</span>
                    <span class="engine-card-badge">CLOUD</span>
                  </div>
                  <p class="engine-card-desc">
                    Multimodal cloud vision adapters authorized by Kavacha privacy boundaries.
                  </p>
                  <code class="engine-card-code">{cloudOcrProvider || "cloud_ocr"}</code>
                </div>

                {/* 1.6 Bank Statement Engine */}
                <div
                  id="custom-engine-bank-statements"
                  class={`pipeline-engine-card ${primaryTask === "bank_consolidation" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("bank_consolidation");
                    onSelectSubtask("bank_consolidation", "instant");
                  }}
                >
                  <div class="engine-card-header">
                    <span class="engine-card-title">Financial Statements</span>
                    <span class="engine-card-badge">BANKING</span>
                  </div>
                  <p class="engine-card-desc">
                    Multi-account transaction parsing, balance reconciliation, and financial ledger normalization.
                  </p>
                  <code class="engine-card-code">bank_statements:instant</code>
                </div>
              </div>

              {/* Cloud Provider Pills if Cloud OCR is selected */}
              {primaryTask === "documents_extraction" && currentSubtask === "cloud_ocr" && (
                <div class="stage-subgroup">
                  <span class="subgroup-label">Cloud Vision Provider:</span>
                  <div class="pipeline-pill-group mini">
                    {CLOUD_OCR_PROVIDERS.map((prov) => (
                      <button
                        key={prov.id}
                        type="button"
                        class={`pipeline-pill-btn ${cloudOcrProvider === prov.id ? "active" : ""}`}
                        onClick={() => onSetCloudOcrProvider(prov.id)}
                      >
                        {prov.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Stage 2: Legacy Font & Script Transduction */}
          <div class="pipeline-stage-card" id="custom-stage-font">
            <div class="stage-header">
              <div class="stage-number">02</div>
              <div class="stage-title-wrap">
                <h4 class="stage-title">Legacy Font & Script Transduction</h4>
                <span class="stage-subtitle">Convert legacy non-Unicode Hindi fonts (Kruti Dev, Devlys) to Unicode</span>
              </div>
            </div>
            <div class="stage-content">
              <div class="pipeline-pill-group">
                <button
                  type="button"
                  id="custom-font-none"
                  class={`pipeline-pill-btn ${!convertLegacyFonts && primaryTask !== "font_conversion" ? "active" : ""}`}
                  onClick={() => {
                    onSetConvertLegacyFonts(false);
                    if (primaryTask === "font_conversion") {
                      onSelectPrimaryTask("documents_extraction");
                      onSelectSubtask("documents_extraction", "native");
                    }
                  }}
                >
                  None / Passthrough
                </button>
                <button
                  type="button"
                  id="custom-font-auto"
                  class={`pipeline-pill-btn ${convertLegacyFonts && (!sourceFont || sourceFont === "auto") && primaryTask !== "font_conversion" ? "active" : ""}`}
                  onClick={() => {
                    onSetConvertLegacyFonts(true);
                    onSetSourceFont("auto");
                    if (primaryTask === "font_conversion") {
                      onSelectPrimaryTask("documents_extraction");
                      onSelectSubtask("documents_extraction", "native");
                    }
                  }}
                >
                  ⚡ Auto-Detect Unicode
                </button>
                <button
                  type="button"
                  id="custom-font-krutidev"
                  class={`pipeline-pill-btn ${convertLegacyFonts && sourceFont === "krutidev010" && primaryTask !== "font_conversion" ? "active" : ""}`}
                  onClick={() => {
                    onSetConvertLegacyFonts(true);
                    onSetSourceFont("krutidev010");
                    if (primaryTask === "font_conversion") {
                      onSelectPrimaryTask("documents_extraction");
                      onSelectSubtask("documents_extraction", "native");
                    }
                  }}
                >
                  🔤 Kruti Dev 010
                </button>
                <button
                  type="button"
                  id="custom-font-devlys"
                  class={`pipeline-pill-btn ${convertLegacyFonts && sourceFont === "devlys010" && primaryTask !== "font_conversion" ? "active" : ""}`}
                  onClick={() => {
                    onSetConvertLegacyFonts(true);
                    onSetSourceFont("devlys010");
                    if (primaryTask === "font_conversion") {
                      onSelectPrimaryTask("documents_extraction");
                      onSelectSubtask("documents_extraction", "native");
                    }
                  }}
                >
                  🔤 Devlys 010
                </button>
                <button
                  type="button"
                  id="custom-font-to-kruti"
                  class={`pipeline-pill-btn ${primaryTask === "font_conversion" && currentSubtask === "unicode_to_krutidev" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("font_conversion");
                    onSelectSubtask("font_conversion", "unicode_to_krutidev");
                  }}
                >
                  Standalone: Unicode → Kruti Dev
                </button>
                <button
                  type="button"
                  id="custom-font-to-devlys"
                  class={`pipeline-pill-btn ${primaryTask === "font_conversion" && currentSubtask === "unicode_to_devlys" ? "active" : ""}`}
                  onClick={() => {
                    onSelectPrimaryTask("font_conversion");
                    onSelectSubtask("font_conversion", "unicode_to_devlys");
                  }}
                >
                  Standalone: Unicode → Devlys
                </button>
              </div>
            </div>
          </div>

          {/* Stage 3: Multilingual Neural Translation */}
          <div class="pipeline-stage-card" id="custom-stage-translation">
            <div class="stage-header">
              <div class="stage-number">03</div>
              <div class="stage-title-wrap">
                <h4 class="stage-title">Multilingual Neural Translation</h4>
                <span class="stage-subtitle">Offline IndicTrans2, OPUS-MT, or Cloud Multimodal AI</span>
              </div>
            </div>
            <div class="stage-content">
              <div class="pipeline-pill-group">
                <button
                  type="button"
                  id="custom-trans-none"
                  class={`pipeline-pill-btn ${primaryTask !== "translation" ? "active" : ""}`}
                  onClick={() => {
                    if (primaryTask === "translation") {
                      onSelectPrimaryTask("documents_extraction");
                      onSelectSubtask("documents_extraction", "native");
                    }
                  }}
                >
                  None / Passthrough
                </button>
                {TRANSLATION_ENGINES.map((eng) => (
                  <button
                    key={eng.id}
                    type="button"
                    id={`custom-trans-${eng.id}`}
                    class={`pipeline-pill-btn ${primaryTask === "translation" && currentSubtask === eng.id ? "active" : ""}`}
                    onClick={() => {
                      onSelectPrimaryTask("translation");
                      onSelectSubtask("translation", eng.id);
                    }}
                  >
                    {eng.label}
                  </button>
                ))}
              </div>

              {primaryTask === "translation" && (
                <div class="stage-subgroup">
                  <span class="subgroup-label">Translation Direction:</span>
                  <div class="pipeline-pill-group mini">
                    <button
                      type="button"
                      id="custom-trans-hi-en"
                      class={`pipeline-pill-btn ${transDirection === "hi_to_en" ? "active" : ""}`}
                      onClick={() => onSetTransDirection("hi_to_en")}
                    >
                      Hindi → English
                    </button>
                    <button
                      type="button"
                      id="custom-trans-en-hi"
                      class={`pipeline-pill-btn ${transDirection === "en_to_hi" ? "active" : ""}`}
                      onClick={() => onSetTransDirection("en_to_hi")}
                    >
                      English → Hindi
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Stage 4: Document Layout & Structural Heuristics */}
          <div class="pipeline-stage-card" id="custom-stage-layout">
            <div class="stage-header">
              <div class="stage-number">04</div>
              <div class="stage-title-wrap">
                <h4 class="stage-title">Document Layout & Structural Heuristics</h4>
                <span class="stage-subtitle">Multi-column flow, table structure, header suppression, statutory legal IDs</span>
              </div>
            </div>
            <div class="stage-content">
              <div class="pipeline-toggle-grid">
                <label class={`pipeline-toggle-card ${layoutAnalysis ? "checked" : ""}`}>
                  <input
                    id="param-layout-analysis"
                    type="checkbox"
                    checked={layoutAnalysis}
                    onChange={(e) => onSetLayoutAnalysis(e.currentTarget.checked)}
                  />
                  <div class="pipeline-toggle-info">
                    <span class="pipeline-toggle-title">Deep Layout Analysis (GNN)</span>
                    <span class="pipeline-toggle-desc">Multi-column flow, table grids, reading order</span>
                  </div>
                </label>

                <label class={`pipeline-toggle-card ${preserveLayout ? "checked" : ""}`}>
                  <input
                    id="param-preserve-layout"
                    type="checkbox"
                    checked={preserveLayout}
                    onChange={(e) => onSetPreserveLayout(e.currentTarget.checked)}
                  />
                  <div class="pipeline-toggle-info">
                    <span class="pipeline-toggle-title">Visual Layout Preservation</span>
                    <span class="pipeline-toggle-desc">Preserve spatial coordinates and bounding boxes</span>
                  </div>
                </label>

                <label class={`pipeline-toggle-card ${skipHeaderFooter ? "checked" : ""}`}>
                  <input
                    id="param-skip-header-footer"
                    type="checkbox"
                    checked={skipHeaderFooter}
                    onChange={(e) => onSetSkipHeaderFooter(e.currentTarget.checked)}
                  />
                  <div class="pipeline-toggle-info">
                    <span class="pipeline-toggle-title">Separate Headers & Footers</span>
                    <span class="pipeline-toggle-desc">Suppress repeated running headers and page footers</span>
                  </div>
                </label>

                <label class={`pipeline-toggle-card ${statutoryEnabled ? "checked" : ""}`}>
                  <input
                    id="param-statutory"
                    type="checkbox"
                    checked={statutoryEnabled}
                    onChange={(e) => onSetStatutoryEnabled(e.currentTarget.checked)}
                  />
                  <div class="pipeline-toggle-info">
                    <span class="pipeline-toggle-title">Statutory Legal ID Detection</span>
                    <span class="pipeline-toggle-desc">Extract PAN, GSTIN, CIN, CNR, Court Case IDs</span>
                  </div>
                </label>
              </div>
            </div>
          </div>

          {/* Stage 5: Neural Accelerator & OCR Parameter Tuning */}
          <div class="pipeline-stage-card" id="custom-stage-tuning">
            <div class="stage-header">
              <div class="stage-number">05</div>
              <div class="stage-title-wrap">
                <h4 class="stage-title">Neural Accelerator & Parameter Tuning</h4>
                <span class="stage-subtitle">Hardware acceleration profile, detection thresholds, and preprocessing filters</span>
              </div>
            </div>
            <div class="stage-content">
              {ocrAction?.parameters && ocrAction.parameters.length > 0 ? (
                <div class="pipeline-tuning-container">
                  {ocrAction.parameters.map((parameter) => (
                    <ActionParameter
                      key={parameter.parameter_id}
                      parameter={parameter}
                      value={ocrCustomParams[parameter.parameter_id] ?? parameter.default_value}
                      onChange={(value) => onSetOcrCustomParam(parameter.parameter_id, value)}
                    />
                  ))}
                </div>
              ) : (
                <p class="engine-card-desc">Hardware auto-tuning active for Intel Core Ultra 5 125H.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

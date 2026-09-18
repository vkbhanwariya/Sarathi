import { ActionParameter } from "./Common";
import type { AvailableActionView } from "../types";
import {
  PRIMARY_TASKS,
  CLOUD_OCR_PROVIDERS,
  TRANSLATION_ENGINES,
  type PrimaryTaskId,
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
  const ocrAction = availableActions.find((a) => a.action_id === "ocr");

  return (
    <div class="tasks-accordion" role="tablist" aria-label="Primary Tasks">
      {PRIMARY_TASKS.map((task) => {
        const isSelected = primaryTask === task.id;
        return (
          <div
            key={task.id}
            class={`accordion-item ${isSelected ? "expanded" : "collapsed"}`}
            data-task={task.id}
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
                <span class="primary-task-icon">{task.icon}</span>
                <div class="primary-task-info">
                  <span class="primary-task-label">{task.label}</span>
                  <span class="primary-task-desc">{task.description}</span>
                </div>
              </div>
              <div class="accordion-header-right">
                {isSelected ? (
                  <span class="accordion-badge accordion-badge--active">Active</span>
                ) : (
                  <span class="accordion-badge accordion-badge--hint">Click to expand</span>
                )}
                <span class={`accordion-chevron ${isSelected ? "open" : ""}`} aria-hidden="true">
                  ▾
                </span>
              </div>
            </button>

            {/* Level 2: Second-Level Progressive Choices Collapsing under this Level 1 Task */}
            {isSelected && (
              <div class="accordion-body">
                {task.id === "documents_extraction" && (
                  <div class="subtasks-container">
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
                              <h4 class="action-card-name">Native Extraction</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>DIGITAL</span>
                            </div>
                            <p class="action-card-desc">
                              Direct digital extraction from PDF, DOCX, XLSX, XLS, CSV. Automatically invokes statutory/legal extraction.
                            </p>
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
                                  <strong>Statutory Extraction</strong>
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
                                  <strong>Clean Output: Separate Running Headers/Footers</strong>
                                </span>
                              </label>
                            </div>
                            <div class="action-card-footer">
                              <span class={`action-dot ${isSel ? "active" : ""}`} />
                              <code class="action-code">read_native</code>
                            </div>
                          </div>
                        );
                      })()}

                      {/* 1.2 Instant OCR */}
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
                              <h4 class="action-card-name">Instant OCR</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>RAPIDOCR</span>
                            </div>
                            <p class="action-card-desc">
                              RapidOCR inference with OpenVINO acceleration. Single pass, bypasses heavy preprocessing.
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
                              <h4 class="action-card-name">Accurate OCR</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>ACCURATE</span>
                            </div>
                            <p class="action-card-desc">
                              Quality-optimized OCR with CLAHE, deskew, binarization, and selective NE-OCR fallback.
                            </p>
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
                                  <strong>Preserve Layout</strong>
                                </span>
                              </label>
                              <label class="toggle-row mini" title="Detect and separate running page headers and footers from continuous narrative text">
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
                                  <strong>Clean Output: Separate Running Headers/Footers</strong>
                                </span>
                              </label>
                            </div>
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
                              External cloud multimodal document recognition with fail-closed Kavacha authorization.
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
                              <h4 class="action-card-name">Custom OCR</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>CUSTOM</span>
                            </div>
                            <p class="action-card-desc">
                              Fine-grained parameter control over OCR engine, language, and preprocessing toggles.
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
                          <h4>Custom OCR Options</h4>
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

                {task.id === "bank_consolidation" && (
                  <div class="subtasks-container">
                    <div class="subtasks-grid">
                      {/* 2.1 Instant Consolidation */}
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
                              Throughput-optimized parsing and standard reconciliation heuristics across financial statements.
                            </p>
                            <div class="action-card-footer">
                              <span class={`action-dot ${isSel ? "active" : ""}`} />
                              <code class="action-code">bank_statements:instant</code>
                            </div>
                          </div>
                        );
                      })()}

                      {/* 2.2 Accurate Consolidation */}
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
                            title={isEnabled ? "Strict running balance verification and deduplication." : (act?.disabled_reason || "Unavailable")}
                          >
                            <div class="action-card-header">
                              <h4 class="action-card-name">Accurate Consolidation</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>ACCURATE</span>
                            </div>
                            <p class="action-card-desc">
                              Strict running balance verification, debit/credit inversion detection, and multi-page pagination deduplication.
                            </p>
                            <div class="action-card-footer">
                              <span class={`action-dot ${isSel ? "active" : ""}`} />
                              <code class="action-code">bank_statements:accurate</code>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                )}

                {task.id === "font_conversion" && (
                  <div class="subtasks-container">
                    <div class="subtasks-grid">
                      {/* 3.1 Legacy to Unicode */}
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
                              <h4 class="action-card-name">Legacy to Unicode</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>UNICODE</span>
                            </div>
                            <p class="action-card-desc">
                              Auto-detects non-Unicode Indian font encodings (KrutiDev, DevLys, Chanakya, Shusha, Shivaji) and converts to standardized Unicode Devanagari.
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

                      {/* 3.2 Unicode to KrutiDev */}
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
                            title={isEnabled ? "Reverses Unicode Devanagari text into legacy KrutiDev 010." : (act?.disabled_reason || "Unavailable")}
                          >
                            <div class="action-card-header">
                              <h4 class="action-card-name">Unicode to KrutiDev</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>KRUTIDEV</span>
                            </div>
                            <p class="action-card-desc">
                              Reverses Unicode Devanagari text into legacy KrutiDev 010 typewriter encoding using precompiled reverse transducers.
                            </p>
                            <div class="action-card-footer">
                              <span class={`action-dot ${isSel ? "active" : ""}`} />
                              <code class="action-code">font_conversion:to_krutidev</code>
                            </div>
                          </div>
                        );
                      })()}

                      {/* 3.3 Unicode to DevLys */}
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
                            title={isEnabled ? "Reverses Unicode Devanagari text into legacy DevLys 010." : (act?.disabled_reason || "Unavailable")}
                          >
                            <div class="action-card-header">
                              <h4 class="action-card-name">Unicode to DevLys</h4>
                              <span class={`action-tag ${isSel ? "active" : ""}`}>DEVLYS</span>
                            </div>
                            <p class="action-card-desc">
                              Reverses Unicode Devanagari text into legacy DevLys 010 typewriter encoding using precompiled reverse transducers.
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

                {task.id === "translation" && (
                  <div class="subtasks-container">
                    {/* Direction selector first */}
                    <div class="translation-direction-toolbar" role="group" aria-label="Translation Direction">
                      <button
                        id="btn-direction-auto"
                        data-dir=""
                        class={`direction-seg-btn ${transDirection === "" ? "active" : ""}`}
                        type="button"
                        onClick={() => onSetTransDirection("")}
                      >
                        ⚡ Auto-Detect Language Direction
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

                    {/* 5 Approved Engine Choices */}
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
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

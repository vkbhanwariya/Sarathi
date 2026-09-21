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
  ocrEngineType: "local" | "cloud";
  ocrModelLang: "devanagari" | "en_v6";
  ocrFallbackToLocal: boolean;
  removeStamps?: boolean;
  preserveProperNouns?: boolean;
  transFallbackToLocal?: boolean;
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
  onSetRemoveStamps?: (enabled: boolean) => void;
  onSetPreserveProperNouns?: (enabled: boolean) => void;
  onSetTransFallbackToLocal?: (fallback: boolean) => void;
  ocrProfile?: "accurate" | "instant";
  onSetOcrProfile?: (profile: "accurate" | "instant") => void;
  onSetOcrCustomParam: (key: string, value: unknown) => void;
  onSetOcrEngineType: (engineType: "local" | "cloud") => void;
  onSetOcrModelLang: (lang: "devanagari" | "en_v6") => void;
  onSetOcrFallbackToLocal: (fallback: boolean) => void;
}

export function TaskSelector({
  primaryTask,
  currentSubtask,
  availableActions,
  cloudOcrProvider,
  transDirection,
  statutoryEnabled,
  convertLegacyFonts,
  layoutAnalysis,
  preserveLayout,
  sourceFont,
  skipHeaderFooter,
  removeStamps = false,
  ocrCustomParams,
  ocrEngineType,
  ocrModelLang,
  ocrFallbackToLocal,
  preserveProperNouns = true,
  transFallbackToLocal = true,
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
  onSetRemoveStamps,
  onSetPreserveProperNouns,
  onSetTransFallbackToLocal,
  ocrProfile = "instant",
  onSetOcrProfile,
  onSetOcrCustomParam,
  onSetOcrEngineType,
  onSetOcrModelLang,
  onSetOcrFallbackToLocal,
}: TaskSelectorProps) {
  const selectedTask = PRIMARY_TASKS.find((task) => task.id === primaryTask);
  const ocrAction = availableActions.find((a) => a.action_id === "ocr");

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
      {/* Primary Workflows Layered Deck */}
      <div class={`tasks-accordion tasks-deck ${primaryTask ? "in-deep-dive" : "in-deck-view"}`} role="group" aria-label="Primary Tasks">
        {primaryTask ? (
          <div class="deep-dive-workspace">
            <button
              id={`btn-task-${primaryTask.replace(/_/g, "-")}`}
              class="primary-task-tab-btn selected-task-heading active"
              aria-label={`Change task: ${selectedTask?.label}`}
              aria-expanded="true"
              type="button"
              onClick={() => onSelectPrimaryTask(null)}
            >
              <div class="selected-task-label-group">
                {renderTaskIcon(primaryTask)}
                <strong class="selected-task-name">{selectedTask?.label}</strong>
              </div>
              <span class="change-task-badge">
                <span class="change-task-arrow">&larr;</span> Change task
              </span>
            </button>

            {/* Selected task modes and settings */}
            {PRIMARY_TASKS
              .filter((task) => primaryTask === task.id)
              .map((task) => (
                <div
                  key={task.id}
                  class="accordion-item expanded active-layer"
                  data-task={task.id}
                >
                  <div class="accordion-body">
                    {/* Task 1: Scan to Word & Document Extraction */}
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
                                title={isEnabled ? "Extract text and tables from digital documents." : (act?.disabled_reason || "Unavailable")}
                              >
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">Native Extraction</span>
                                  <span class={`action-tag ${isSel ? "active" : ""}`}>FAST · VECTOR</span>
                                </button>
                                <p class="action-card-desc">
                                  Extract text and tables directly from digital PDFs, Word, and Excel without OCR.
                                </p>
                                {isSel && (
                                  <div class="ocr-add-ons-section" style={{ marginTop: "12px" }} onClick={(e) => e.stopPropagation()}>
                                    <span class="ocr-section-subtitle">Document Layout &amp; Structure</span>
                                    <div class="ocr-toggles-grid">
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
                                  </div>
                                )}
                              </div>
                            );
                          })()}

                          {/* 1.2 OCR Document Recognition */}
                          {(() => {
                            const act = availableActions.find((a) => a.action_id === "ocr");
                            const isEnabled = act ? act.is_enabled : true;
                            const isSel = currentSubtask === "ocr" || currentSubtask === "accurate_ocr" || currentSubtask === "instant_ocr" || currentSubtask === "custom_ocr" || currentSubtask === "cloud_ocr";
                            const tagLabel = ocrEngineType === "cloud" ? "CLOUD AI" : "LOCAL NEURAL";
                            return (
                              <div
                                key="ocr"
                                id="subtask-ocr"
                                data-subtask="ocr"
                                data-req="ocr"
                                class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                onClick={() => onSelectSubtask("documents_extraction", "ocr")}
                                title={isEnabled ? "Neural optical character recognition for scanned docs and images." : (act?.disabled_reason || "Unavailable")}
                              >
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">OCR Document Recognition</span>
                                  <span class={`action-tag ${isSel ? "active" : ""}`}>{tagLabel}</span>
                                </button>
                                {isSel && (
                                  <div class="ocr-card-details" onClick={(e) => e.stopPropagation()}>
                                    {/* 1. Mode Row (Instant vs Accurate) */}
                                    <div class="ocr-group-row">
                                      <span class="ocr-group-label">Mode:</span>
                                      <div class="ocr-group-toggles">
                                        <button
                                          id="btn-ocr-profile-instant"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrProfile === "instant" ? "active" : ""}`}
                                          title="Instant profile 150 DPI (Fast)"
                                          onClick={() => {
                                            if (onSetOcrProfile) onSetOcrProfile("instant");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>⚡ Instant (150 DPI)</strong></span>
                                        </button>

                                        <button
                                          id="btn-ocr-profile-accurate"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrProfile === "accurate" ? "active" : ""}`}
                                          title="Accurate profile 200 DPI (High Fidelity)"
                                          onClick={() => {
                                            if (onSetOcrProfile) onSetOcrProfile("accurate");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>🎯 Accurate (200 DPI)</strong></span>
                                        </button>
                                      </div>
                                    </div>

                                    {/* 2. Inference Engine */}
                                    <div class="ocr-group-row">
                                      <span class="ocr-group-label">Engine:</span>
                                      <div class="ocr-group-toggles">
                                        <button
                                          id="btn-ocr-engine-local"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrEngineType === "local" ? "active" : ""}`}
                                          title="Local OpenVINO Arc iGPU"
                                          onClick={() => {
                                            onSetOcrEngineType("local");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>⚡ Local (Arc iGPU)</strong></span>
                                        </button>

                                        <button
                                          id="btn-ocr-engine-cloud"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrEngineType === "cloud" ? "active" : ""}`}
                                          title="Cloud Multimodal AI"
                                          onClick={() => {
                                            onSetOcrEngineType("cloud");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>☁ Cloud AI</strong></span>
                                        </button>
                                      </div>
                                    </div>

                                    {/* Cloud Provider Pill (Directly underneath Cloud OCR button) */}
                                    <div class="cloud-pill-row">
                                      <div class="cloud-provider-pills" role="group" aria-label="Cloud Provider">
                                        {CLOUD_OCR_PROVIDERS.map((cp) => {
                                          const cloudAct = availableActions.find((a) => a.action_id === cp.id);
                                          const isChipAvail = cloudAct ? cloudAct.is_enabled : false;
                                          const isChipActive = ocrEngineType === "cloud" && cloudOcrProvider === cp.id;
                                          return (
                                            <button
                                              key={cp.id}
                                              id={`chip-${cp.id.replace(/_/g, "-")}`}
                                              type="button"
                                              class={`cloud-pill-btn ${isChipActive ? "active" : ""}`}
                                              disabled={!isChipAvail}
                                              title={isChipAvail ? `${cp.label} Cloud OCR` : (cloudAct?.disabled_reason || "Unavailable")}
                                              onClick={() => {
                                                onSetOcrEngineType("cloud");
                                                onSetCloudOcrProvider(cp.id);
                                                onSelectSubtask("documents_extraction", "ocr");
                                              }}
                                            >
                                              {cp.label}
                                            </button>
                                          );
                                        })}
                                      </div>

                                      <label class="toggle-row mini" title="Fallback to local OpenVINO if Cloud fails">
                                        <input
                                          id="param-ocr-fallback-to-local"
                                          type="checkbox"
                                          checked={ocrFallbackToLocal}
                                          onChange={(e) => onSetOcrFallbackToLocal(e.currentTarget.checked)}
                                        />
                                        <span><strong>Fallback to local</strong></span>
                                      </label>
                                    </div>

                                    {/* 3. Language Model */}
                                    <div class="ocr-group-row">
                                      <span class="ocr-group-label">Model:</span>
                                      <div class="ocr-group-toggles">
                                        <button
                                          id="btn-ocr-lang-devanagari"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrModelLang === "devanagari" ? "active" : ""}`}
                                          title="PP-OCRv5 Devanagari Hindi"
                                          onClick={() => {
                                            onSetOcrEngineType("local");
                                            onSetOcrModelLang("devanagari");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Devanagari (Hindi)</strong></span>
                                        </button>

                                        <button
                                          id="btn-ocr-lang-en-v6"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrModelLang === "en_v6" ? "active" : ""}`}
                                          title="PP-OCRv6 English"
                                          onClick={() => {
                                            onSetOcrEngineType("local");
                                            onSetOcrModelLang("en_v6");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>English</strong></span>
                                        </button>
                                      </div>
                                    </div>

                                    {/* 4. Accuracy & Document Structure Toggles */}
                                    <div class="ocr-options-grid">
                                      <label class="toggle-row mini" title="Preserve layout geometry">
                                        <input
                                          id="param-preserve-layout"
                                          type="checkbox"
                                          checked={preserveLayout}
                                          onChange={(e) => {
                                            onSetPreserveLayout(e.currentTarget.checked);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        />
                                        <span>
                                          <strong>Preserve layout</strong>
                                        </span>
                                      </label>

                                      <label class="toggle-row mini" title="Separate running headers and footers">
                                        <input
                                          id="param-ocr-skip-header-footer"
                                          type="checkbox"
                                          checked={skipHeaderFooter}
                                          onChange={(e) => {
                                            onSetSkipHeaderFooter(e.currentTarget.checked);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        />
                                        <span>
                                          <strong>Headers / Footers</strong>
                                        </span>
                                      </label>

                                      <label class="toggle-row mini" title="Extract and validate statutory IDs">
                                        <input
                                          id="param-ocr-statutory"
                                          type="checkbox"
                                          checked={statutoryEnabled}
                                          onChange={(e) => {
                                            onSetStatutoryEnabled(e.currentTarget.checked);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        />
                                        <span>
                                          <strong>Statutory IDs</strong>
                                        </span>
                                      </label>

                                      <label class="toggle-row mini" title="Convert legacy Hindi fonts to Unicode">
                                        <input
                                          id="param-ocr-convert-legacy-fonts"
                                          type="checkbox"
                                          checked={convertLegacyFonts}
                                          onChange={(e) => {
                                            onSetConvertLegacyFonts(e.currentTarget.checked);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        />
                                        <span>
                                          <strong>Legacy fonts</strong>
                                        </span>
                                      </label>

                                      <label class="toggle-row mini" title="Suppress rubber stamps and seals">
                                        <input
                                          id="param-ocr-remove-stamps"
                                          type="checkbox"
                                          checked={removeStamps}
                                          onChange={(e) => {
                                            if (onSetRemoveStamps) onSetRemoveStamps(e.currentTarget.checked);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        />
                                        <span>
                                          <strong>Stamp suppression</strong>
                                        </span>
                                      </label>
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })()}
                        </div>
                      </div>
                    )}

                    {/* Task 2: Font Standardizer (Word & Excel) */}
                    {task.id === "font_conversion" && (
                      <div class="subtasks-container">
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
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">Auto detect to Unicode</span>
                                </button>
                                <p class="action-card-desc">
                                  Convert legacy Hindi fonts in Word and Excel to Unicode.
                                </p>
                                {isSel && (
                                  <details class="more-options task-settings" onClick={(e) => e.stopPropagation()}>
                                    <summary>Settings</summary>
                                    <div class="subtask-options-row">
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
                                  </details>
                                )}
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
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">Convert to KrutiDev</span>
                                </button>
                                <p class="action-card-desc">
                                  Transduces Unicode text back into legacy KrutiDev 010 for older government printing portals or typewriter submissions.
                                </p>
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
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">Convert to DevLys</span>
                                </button>
                                <p class="action-card-desc">
                                  Transduces Unicode text back into legacy DevLys 010 for governmental typewriter compatibility.
                                </p>
                              </div>
                            );
                          })()}
                        </div>
                      </div>
                    )}

                    {/* Task 3: Document Translation (Word, PDF & Excel) */}
                    {task.id === "translation" && (
                      <div class="subtasks-container">
                        {/* Translation Legal Integrity Bar */}
                        <div class="translation-integrity-features-bar">
                          <span class="integrity-chip">✓ Statutory Legal Glossaries</span>
                          <span class="integrity-chip">✓ Proper Noun Preservation</span>
                          <span class="integrity-chip">✓ Case Law &amp; Citation Protector</span>
                          <span class="integrity-chip">⚡ AVX-VNNI Neural Speed</span>
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
                            Auto-detect
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

                        {/* Legal Invariants Toggles in Front */}
                        <div class="translation-add-ons-section">
                          <span class="ocr-section-subtitle">Legal Fidelity &amp; Terminology Protection</span>
                          <div class="ocr-toggles-grid">
                            <label class="toggle-row mini" title="Normalize and align legal terms using on-device statutory glossaries">
                              <input
                                id="param-trans-statutory"
                                type="checkbox"
                                checked={statutoryEnabled}
                                onChange={(e) => {
                                  onSetStatutoryEnabled(e.currentTarget.checked);
                                }}
                              />
                              <span>
                                <strong>Statutory Terminology Harmonization</strong>
                              </span>
                            </label>
                            <label class="toggle-row mini" title="Preserve Indian proper names and kinship designations from semantic hallucination">
                              <input
                                id="param-trans-proper-nouns"
                                type="checkbox"
                                checked={preserveProperNouns}
                                onChange={(e) => {
                                  if (onSetPreserveProperNouns) onSetPreserveProperNouns(e.currentTarget.checked);
                                }}
                              />
                              <span>
                                <strong>Proper Noun &amp; Name Preservation</strong>
                              </span>
                            </label>
                            {(() => {
                              const selEng = TRANSLATION_ENGINES.find((e) => e.id === currentSubtask);
                              return Boolean(selEng?.isCloud) ? (
                                <label class="toggle-row mini" title="Automatically fall back to local IndicTrans2 if cloud API rate limits or network issues occur">
                                  <input
                                    id="param-trans-fallback-local"
                                    type="checkbox"
                                    checked={transFallbackToLocal}
                                    onChange={(e) => {
                                      if (onSetTransFallbackToLocal) onSetTransFallbackToLocal(e.currentTarget.checked);
                                    }}
                                  />
                                  <span>
                                    <strong>Fallback to Local IndicTrans2</strong>
                                  </span>
                                </label>
                              ) : null;
                            })()}
                          </div>
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
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">{eng.label}</span>
                                  <span class={`action-tag ${isSel ? "active" : ""}`}>{eng.tag || (eng.isCloud ? "CLOUD AI" : "LOCAL NEURAL")}</span>
                                </button>
                                <p class="action-card-desc">{isEnabled ? eng.desc : (act?.disabled_reason || "Unavailable")}</p>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Task 4: Bank Statement Consolidation & Audit */}
                    {task.id === "bank_consolidation" && (
                      <div class="subtasks-container">
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
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">Accurate Consolidation</span>
                                  <span class={`action-tag ${isSel ? "active" : ""}`}>AUDIT-GRADE</span>
                                </button>
                                <p class="action-card-desc">
                                  Strict double-entry balance arithmetic verification, UTR/IFSC auto-repair, and master Excel workbook with 1-page executive memo.
                                </p>
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
                                <button class="action-card-header" type="button" aria-pressed={isSel}>
                                  <span class="action-card-name">Instant Consolidation</span>
                                  <span class={`action-tag ${isSel ? "active" : ""}`}>FAST</span>
                                </button>
                                <p class="action-card-desc">
                                  Throughput-optimized parsing across financial statements using standard layout heuristics.
                                </p>
                              </div>
                            );
                          })()}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
          </div>
        ) : (
          <div class="workflow-columns-grid">
            {PRIMARY_TASKS.map((task) => (
              <div
                key={task.id}
                class="accordion-item collapsed workflow-col-card"
                data-task={task.id}
              >
                <button
                  id={`btn-task-${task.id.replace(/_/g, "-")}`}
                  data-task={task.id}
                  class="primary-task-tab-btn col-card-btn"
                  role="tab"
                  aria-selected={false}
                  aria-expanded={false}
                  type="button"
                  onClick={() => onSelectPrimaryTask(task.id)}
                >
                  <span class="col-card-icon">{renderTaskIcon(task.id)}</span>
                  <div class="col-card-body">
                    <div class="col-card-title-row">
                      <h3 class="col-card-title">{task.label}</h3>
                      {task.badge && <span class="col-card-tag">{task.badge}</span>}
                    </div>
                    <p class="col-card-desc">{task.description}</p>
                  </div>
                  <span class="col-arrow" aria-hidden="true">→</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

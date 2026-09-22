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
                                  <div class="ocr-card-details" onClick={(e) => e.stopPropagation()}>
                                    <div class="ocr-feature-box">
                                      <span class="ocr-feature-box-header">Document Processing</span>
                                      <div class="ocr-toggles-grid">
                                        <button
                                          id="param-convert-legacy-fonts"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${convertLegacyFonts ? "active" : ""}`}
                                          onClick={() => {
                                            onSetConvertLegacyFonts(!convertLegacyFonts);
                                            onSelectSubtask("documents_extraction", "native");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Legacy Fonts → Unicode</strong></span>
                                        </button>
                                        <button
                                          id="param-layout-analysis"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${layoutAnalysis ? "active" : ""}`}
                                          title="Use Graph Neural Networks for multi-column flow, table grids, and semantic headers"
                                          onClick={() => {
                                            onSetLayoutAnalysis(!layoutAnalysis);
                                            onSelectSubtask("documents_extraction", "native");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Deep Layout Analysis (GNN)</strong></span>
                                        </button>
                                      </div>
                                    </div>

                                    <div class="ocr-feature-box">
                                      <span class="ocr-feature-box-header">Legal &amp; Structure</span>
                                      <div class="ocr-toggles-grid">
                                        <button
                                          id="param-statutory"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${statutoryEnabled ? "active" : ""}`}
                                          onClick={() => {
                                            onSetStatutoryEnabled(!statutoryEnabled);
                                            onSelectSubtask("documents_extraction", "native");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Statutory ID Detection</strong></span>
                                        </button>
                                        <button
                                          id="param-skip-header-footer"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${skipHeaderFooter ? "active" : ""}`}
                                          title="Detect and separate running page headers and footers from continuous narrative text"
                                          onClick={() => {
                                            onSetSkipHeaderFooter(!skipHeaderFooter);
                                            onSelectSubtask("documents_extraction", "native");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Headers / Footers</strong></span>
                                        </button>
                                      </div>
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
                                    {/* Box 1: Mode */}
                                    <div class="ocr-feature-box">
                                      <span class="ocr-feature-box-header">Mode</span>
                                      <div class="ocr-group-toggles">
                                        <button
                                          id="btn-ocr-profile-accurate"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrProfile === "accurate" ? "active" : ""}`}
                                          title="Toggle Accurate mode (default is Instant)"
                                          onClick={() => {
                                            if (onSetOcrProfile) onSetOcrProfile(ocrProfile === "accurate" ? "instant" : "accurate");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>🎯 Accurate</strong></span>
                                        </button>
                                      </div>
                                    </div>

                                    {/* Box 2: Inference Engine */}
                                    <div class="ocr-feature-box">
                                      <span class="ocr-feature-box-header">Inference Engine</span>
                                      <div class="ocr-group-toggles">
                                        <button
                                          id="btn-ocr-engine-cloud"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${ocrEngineType === "cloud" ? "active" : ""}`}
                                          title="Enable Cloud AI (Gemini, Mistral, Azure) or stay on Local Arc iGPU"
                                          onClick={() => {
                                            onSetOcrEngineType(ocrEngineType === "cloud" ? "local" : "cloud");
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>☁ Cloud AI</strong></span>
                                        </button>
                                      </div>

                                      {ocrEngineType === "cloud" && (
                                        <div class="cloud-pill-row">
                                          <div class="cloud-provider-pills" role="group" aria-label="Cloud Provider">
                                            {CLOUD_OCR_PROVIDERS.map((cp) => {
                                              const cloudAct = availableActions.find((a) => a.action_id === cp.id);
                                              const isChipAvail = cloudAct ? cloudAct.is_enabled : false;
                                              const isChipActive = cloudOcrProvider === cp.id;
                                              return (
                                                <button
                                                  key={cp.id}
                                                  id={`chip-${cp.id.replace(/_/g, "-")}`}
                                                  type="button"
                                                  class={`cloud-pill-btn ${isChipActive ? "active" : ""}`}
                                                  disabled={!isChipAvail}
                                                  title={isChipAvail ? `${cp.label} Cloud OCR` : (cloudAct?.disabled_reason || "Unavailable")}
                                                  onClick={() => {
                                                    onSetCloudOcrProvider(cp.id);
                                                    onSelectSubtask("documents_extraction", "ocr");
                                                  }}
                                                >
                                                  {cp.label}
                                                </button>
                                              );
                                            })}
                                          </div>

                                          <button
                                            id="param-ocr-fallback-to-local"
                                            type="button"
                                            class={`toggle-row mini toggle-switch-btn ${ocrFallbackToLocal ? "active" : ""}`}
                                            title="Fallback to local OpenVINO if Cloud fails"
                                            onClick={() => onSetOcrFallbackToLocal(!ocrFallbackToLocal)}
                                          >
                                            <span class="toggle-switch-slider"></span>
                                            <span><strong>Fallback to local</strong></span>
                                          </button>
                                        </div>
                                      )}
                                    </div>

                                    {/* Box 3: Language Model */}
                                    <div class="ocr-feature-box">
                                      <span class="ocr-feature-box-header">Language Model</span>
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

                                    {/* Box 4: Document Structure & Legal Fidelity */}
                                    <div class="ocr-feature-box">
                                      <span class="ocr-feature-box-header">Structure &amp; Fidelity</span>
                                      <div class="ocr-toggles-grid">
                                        <button
                                          id="param-preserve-layout"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${preserveLayout ? "active" : ""}`}
                                          title="Preserve layout geometry"
                                          onClick={() => {
                                            onSetPreserveLayout(!preserveLayout);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Preserve layout</strong></span>
                                        </button>

                                        <button
                                          id="param-ocr-skip-header-footer"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${skipHeaderFooter ? "active" : ""}`}
                                          title="Separate running headers and footers"
                                          onClick={() => {
                                            onSetSkipHeaderFooter(!skipHeaderFooter);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Headers / Footers</strong></span>
                                        </button>

                                        <button
                                          id="param-ocr-statutory"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${statutoryEnabled ? "active" : ""}`}
                                          title="Extract and validate statutory IDs"
                                          onClick={() => {
                                            onSetStatutoryEnabled(!statutoryEnabled);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Statutory IDs</strong></span>
                                        </button>

                                        <button
                                          id="param-ocr-convert-legacy-fonts"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${convertLegacyFonts ? "active" : ""}`}
                                          title="Convert legacy Hindi fonts to Unicode"
                                          onClick={() => {
                                            onSetConvertLegacyFonts(!convertLegacyFonts);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Legacy fonts</strong></span>
                                        </button>

                                        <button
                                          id="param-ocr-remove-stamps"
                                          type="button"
                                          class={`toggle-row mini toggle-switch-btn ${removeStamps ? "active" : ""}`}
                                          title="Suppress rubber stamps and seals"
                                          onClick={() => {
                                            if (onSetRemoveStamps) onSetRemoveStamps(!removeStamps);
                                            onSelectSubtask("documents_extraction", "ocr");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Stamp suppression</strong></span>
                                        </button>
                                      </div>
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
                                  <div class="ocr-card-details" onClick={(e) => e.stopPropagation()}>
                                    <div class="ocr-feature-box">
                                      <span class="ocr-feature-box-header">Source Font</span>
                                      <label class="field mini" style={{ margin: 0 }}>
                                        <select
                                          id="param-source-font"
                                          value={sourceFont}
                                          onChange={(e) => onSetSourceFont(e.currentTarget.value)}
                                          style={{ padding: "4px 8px", fontSize: "11px", borderRadius: "6px", border: "1px solid #e2e8f0" }}
                                        >
                                          <option value="">Auto-Detect</option>
                                          <option value="krutidev010">KrutiDev 010 / DevLys</option>
                                          <option value="chanakya010">Chanakya</option>
                                          <option value="shusha010">Shusha</option>
                                          <option value="shivaji010">Shivaji</option>
                                        </select>
                                      </label>
                                    </div>
                                  </div>
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
                        {/* Capabilities Bar */}
                        <div class="ocr-feature-box" style={{ background: "rgba(238, 242, 255, 0.5)" }}>
                          <span class="ocr-feature-box-header">Capabilities</span>
                          <div class="integrity-chips-row">
                            <span class="integrity-chip trans">✓ Statutory Legal Glossaries</span>
                            <span class="integrity-chip trans">✓ Proper Noun Preservation</span>
                            <span class="integrity-chip trans">✓ Case Law &amp; Citation Protector</span>
                            <span class="integrity-chip trans">⚡ AVX-VNNI Neural Speed</span>
                          </div>
                        </div>

                        {/* Direction */}
                        <div class="ocr-feature-box">
                          <span class="ocr-feature-box-header">Direction</span>
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
                        </div>

                        {/* Legal Fidelity */}
                        <div class="ocr-feature-box">
                          <span class="ocr-feature-box-header">Legal Fidelity</span>
                          <div class="ocr-toggles-grid">
                            <button
                              id="param-trans-statutory"
                              type="button"
                              class={`toggle-row mini toggle-switch-btn ${statutoryEnabled ? "active" : ""}`}
                              title="Normalize and align legal terms using on-device statutory glossaries"
                              onClick={() => onSetStatutoryEnabled(!statutoryEnabled)}
                            >
                              <span class="toggle-switch-slider"></span>
                              <span><strong>Statutory Terminology</strong></span>
                            </button>
                            <button
                              id="param-trans-proper-nouns"
                              type="button"
                              class={`toggle-row mini toggle-switch-btn ${preserveProperNouns ? "active" : ""}`}
                              title="Preserve Indian proper names and kinship designations from semantic hallucination"
                              onClick={() => { if (onSetPreserveProperNouns) onSetPreserveProperNouns(!preserveProperNouns); }}
                            >
                              <span class="toggle-switch-slider"></span>
                              <span><strong>Proper Noun Preservation</strong></span>
                            </button>
                            {(() => {
                              const selEng = TRANSLATION_ENGINES.find((e) => e.id === currentSubtask);
                              return Boolean(selEng?.isCloud) ? (
                                <button
                                  id="param-trans-fallback-local"
                                  type="button"
                                  class={`toggle-row mini toggle-switch-btn ${transFallbackToLocal ? "active" : ""}`}
                                  title="Automatically fall back to local IndicTrans2 if cloud API rate limits or network issues occur"
                                  onClick={() => { if (onSetTransFallbackToLocal) onSetTransFallbackToLocal(!transFallbackToLocal); }}
                                >
                                  <span class="toggle-switch-slider"></span>
                                  <span><strong>Fallback to Local IndicTrans2</strong></span>
                                </button>
                              ) : null;
                            })()}
                          </div>
                        </div>

                        {/* Engine Choices */}
                        <div class="ocr-feature-box">
                          <span class="ocr-feature-box-header">Translation Engine</span>
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
                      </div>
                    )}

                    {/* Task 4: Bank Statement Consolidation & Audit */}
                    {task.id === "bank_consolidation" && (
                      <div class="subtasks-container">
                        {/* Capabilities Bar */}
                        <div class="ocr-feature-box" style={{ background: "rgba(236, 253, 245, 0.5)" }}>
                          <span class="ocr-feature-box-header">Verification</span>
                          <div class="integrity-chips-row">
                            <span class="integrity-chip">✓ Double-Entry Verified</span>
                            <span class="integrity-chip">✓ UTR &amp; IFSC Auto-Repair</span>
                            <span class="integrity-chip">✓ Deduplication</span>
                            <span class="integrity-chip">📑 1-Page Audit Memo</span>
                          </div>
                        </div>

                        {/* Mode */}
                        <div class="ocr-feature-box">
                          <span class="ocr-feature-box-header">Consolidation Mode</span>
                          <div class="ocr-group-toggles">
                            <button
                              id="btn-bank-mode-accurate"
                              type="button"
                              class={`toggle-row mini toggle-switch-btn ${currentSubtask === "accurate" ? "active" : ""}`}
                              title="Toggle Accurate mode (default is Instant)"
                              onClick={() => onSelectSubtask("bank_consolidation", currentSubtask === "accurate" ? "instant" : "accurate")}
                            >
                              <span class="toggle-switch-slider"></span>
                              <span><strong>🎯 Accurate (Audit-Grade)</strong></span>
                            </button>
                          </div>
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

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
                                          title="Use high-performance Rust layout engine for multi-column flow, table grids, and reading order"
                                          onClick={() => {
                                            onSetLayoutAnalysis(!layoutAnalysis);
                                            onSelectSubtask("documents_extraction", "native");
                                          }}
                                        >
                                          <span class="toggle-switch-slider"></span>
                                          <span><strong>Deep Layout Analysis (Xberg)</strong></span>
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
                        {/* Box 1: Source Font */}
                        <div class="ocr-feature-box">
                          <span class="ocr-feature-box-header">Source Font</span>
                          <div class="ocr-group-toggles">
                            <button
                              id="btn-font-source-hint"
                              type="button"
                              class={`toggle-row mini toggle-switch-btn ${sourceFont ? "active" : ""}`}
                              title="Specify source font instead of auto-detecting"
                              onClick={() => {
                                onSetSourceFont(sourceFont ? "" : "krutidev010");
                              }}
                            >
                              <span class="toggle-switch-slider"></span>
                              <span><strong>Manual Font Hint</strong></span>
                            </button>
                          </div>

                          {sourceFont && (
                            <div class="cloud-pill-row">
                              <div class="cloud-provider-pills" role="group" aria-label="Source Font">
                                {[
                                  { id: "krutidev010", label: "KrutiDev" },
                                  { id: "chanakya010", label: "Chanakya" },
                                  { id: "shusha010", label: "Shusha" },
                                  { id: "shivaji010", label: "Shivaji" },
                                ].map((f) => (
                                  <button
                                    key={f.id}
                                    id={`chip-font-${f.id}`}
                                    type="button"
                                    class={`cloud-pill-btn ${sourceFont === f.id ? "active" : ""}`}
                                    onClick={() => onSetSourceFont(f.id)}
                                  >
                                    {f.label}
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Box 2: Conversion Direction */}
                        <div class="ocr-feature-box">
                          <span class="ocr-feature-box-header">Conversion</span>
                          <div class="ocr-group-toggles">
                            <button
                              id="btn-font-to-legacy"
                              type="button"
                              class={`toggle-row mini toggle-switch-btn ${currentSubtask !== "legacy_to_unicode" ? "active" : ""}`}
                              title="Toggle Convert to Legacy (default is Legacy → Unicode)"
                              onClick={() => {
                                if (currentSubtask === "legacy_to_unicode") {
                                  onSelectSubtask("font_conversion", "unicode_to_krutidev");
                                } else {
                                  onSelectSubtask("font_conversion", "legacy_to_unicode");
                                }
                              }}
                            >
                              <span class="toggle-switch-slider"></span>
                              <span><strong>Convert to Legacy</strong></span>
                            </button>
                          </div>

                          {currentSubtask !== "legacy_to_unicode" && (
                            <div class="cloud-pill-row">
                              <div class="cloud-provider-pills" role="group" aria-label="Legacy Target">
                                <button
                                  id="chip-font-krutidev"
                                  type="button"
                                  class={`cloud-pill-btn ${currentSubtask === "unicode_to_krutidev" ? "active" : ""}`}
                                  onClick={() => onSelectSubtask("font_conversion", "unicode_to_krutidev")}
                                >
                                  KrutiDev
                                </button>
                                <button
                                  id="chip-font-devlys"
                                  type="button"
                                  class={`cloud-pill-btn ${currentSubtask === "unicode_to_devlys" ? "active" : ""}`}
                                  onClick={() => onSelectSubtask("font_conversion", "unicode_to_devlys")}
                                >
                                  DevLys
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Task 3: Document Translation (Word, PDF & Excel) */}
                    {task.id === "translation" && (
                      <div class="subtasks-container">
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

                        {/* Engine */}
                        <div class="ocr-feature-box">
                          <span class="ocr-feature-box-header">Inference Engine</span>
                          <div class="ocr-group-toggles">
                            <button
                              id="btn-trans-krutrim"
                              type="button"
                              class="toggle-row mini toggle-switch-btn active"
                              title="Krutrim-Translate 4096-token CTranslate2 engine (Optimized for legal context)"
                              onClick={() => {
                                onSelectSubtask("translation", "krutrim");
                              }}
                            >
                              <span class="toggle-switch-slider"></span>
                              <span><strong>Krutrim-Translate (4096 Context)</strong></span>
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
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Task 4: Bank Statement Consolidation & Audit */}
                    {task.id === "bank_consolidation" && (
                      <div class="subtasks-container">
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

export type PrimaryTaskId =
  | "documents_extraction"
  | "bank_consolidation"
  | "font_conversion"
  | "translation";

export interface PrimaryTaskDef {
  id: PrimaryTaskId;
  label: string;
  icon: string;
  description: string;
  badge?: string;
}

export const PRIMARY_TASKS: readonly PrimaryTaskDef[] = [
  {
    id: "documents_extraction",
    label: "Documents Extraction",
    icon: "📄",
    description: "Scanned & digital documents to Word (.docx) and Excel (.xlsx)",
    badge: "DOCX / XLSX",
  },
  {
    id: "bank_consolidation",
    label: "Bank Account Consolidation",
    icon: "🏦",
    description: "Consolidate multi-bank statements into a verified Excel ledger",
    badge: "AUDIT",
  },
  {
    id: "font_conversion",
    label: "Font Conversion",
    icon: "🔤",
    description: "Legacy KrutiDev & Devlys to clean Unicode (.docx & .xlsx)",
    badge: "UNICODE",
  },
  {
    id: "translation",
    label: "Translation",
    icon: "🌐",
    description: "Hindi ↔ English translation with statutory glossary",
    badge: "HI ↔ EN",
  },
];

export interface CloudOcrProviderDef {
  id: string;
  label: string;
}

export const CLOUD_OCR_PROVIDERS: readonly CloudOcrProviderDef[] = [
  { id: "gemini_ocr", label: "Gemini" },
  { id: "mistral_ocr", label: "Mistral" },
  { id: "azure_ocr", label: "Azure" },
];

export interface TranslationEngineDef {
  id: string;
  actionId: string;
  label: string;
  tag: string;
  isCloud: boolean;
  desc: string;
  code: string;
}

export const TRANSLATION_ENGINES: readonly TranslationEngineDef[] = [
  {
    id: "indictrans2",
    actionId: "translation",
    label: "IndicTrans2 (Local)",
    tag: "INDICTRANS2",
    isCloud: false,
    desc: "AI4Bharat IndicTrans2 local Transformer. Optimized for high-fidelity 22 Indian languages.",
    code: "translation:indictrans2",
  },
  {
    id: "opus_mt",
    actionId: "translation",
    label: "Helsinki OPUS-MT (Local)",
    tag: "OPUS-MT",
    isCloud: false,
    desc: "Fast Marian-based neural translation engine running fully offline and local.",
    code: "translation:opus_mt",
  },
  {
    id: "gemini",
    actionId: "gemini_translation",
    label: "Google Gemini (Cloud)",
    tag: "GEMINI",
    isCloud: true,
    desc: "Google Gemini multimodal translation adapter. High context multilingual reasoning.",
    code: "gemini_translation",
  },
  {
    id: "mistral",
    actionId: "mistral_translation",
    label: "Mistral (Cloud)",
    tag: "MISTRAL",
    isCloud: true,
    desc: "Mistral AI European cloud translation adapter. Authorized by Kavacha.",
    code: "mistral_translation",
  },
  {
    id: "azure",
    actionId: "azure_translation",
    label: "Azure AI (Cloud)",
    tag: "AZURE",
    isCloud: true,
    desc: "Microsoft Azure AI Translator cloud service. Enterprise translation backbone.",
    code: "azure_translation",
  },
];

export interface BackendMapping {
  requirement: string;
  profile: string;
}

export function resolveBackendMapping(
  primaryTask: PrimaryTaskId | null,
  currentSubtask: string | undefined,
  options: {
    layoutAnalysis?: boolean;
    preserveLayout?: boolean;
    cloudOcrProvider?: string;
    ocrProfile?: string;
    ocrEngineType?: "local" | "cloud";
  }
): BackendMapping | null {
  if (!primaryTask || !currentSubtask) return null;
  if (primaryTask === "documents_extraction") {
    if (currentSubtask === "native") {
      return {
        requirement: "read_native",
        profile: options.layoutAnalysis ? "layout_preserving" : "instant",
      };
    }
    if (currentSubtask === "ocr") {
      if (options.ocrEngineType === "cloud") {
        return {
          requirement: options.cloudOcrProvider || "gemini_ocr",
          profile: "instant",
        };
      }
      return {
        requirement: "ocr",
        profile: options.preserveLayout ? "layout_preserving" : (options.ocrProfile || "instant"),
      };
    }
    if (currentSubtask === "instant_ocr") {
      return { requirement: "ocr", profile: "instant" };
    }
    if (currentSubtask === "accurate_ocr") {
      return {
        requirement: "ocr",
        profile: options.preserveLayout ? "layout_preserving" : "accurate",
      };
    }
    if (currentSubtask === "cloud_ocr") {
      return {
        requirement: options.cloudOcrProvider || "gemini_ocr",
        profile: "instant",
      };
    }
    if (currentSubtask === "custom_ocr") {
      return {
        requirement: "ocr",
        profile: options.ocrProfile || "custom",
      };
    }
    return { requirement: "read_native", profile: "instant" };
  }
  if (primaryTask === "bank_consolidation") {
    return {
      requirement: "bank_statements",
      profile: currentSubtask === "accurate" ? "accurate" : "instant",
    };
  }
  if (primaryTask === "font_conversion") {
    return { requirement: "font_conversion", profile: "instant" };
  }
  if (primaryTask === "translation") {
    if (currentSubtask === "opus_mt") return { requirement: "translation", profile: "instant" };
    if (currentSubtask === "gemini") return { requirement: "gemini_translation", profile: "instant" };
    if (currentSubtask === "mistral") return { requirement: "mistral_translation", profile: "instant" };
    if (currentSubtask === "azure") return { requirement: "azure_translation", profile: "instant" };
    return { requirement: "translation", profile: "instant" };
  }
  return { requirement: "read_native", profile: "instant" };
}

export function isCloudAction(actionId: string): boolean {
  return (
    actionId.startsWith("gemini_") ||
    actionId.startsWith("azure_") ||
    actionId.startsWith("mistral_") ||
    actionId.includes("cloud")
  );
}

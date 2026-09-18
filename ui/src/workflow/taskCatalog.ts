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
}

export const PRIMARY_TASKS: readonly PrimaryTaskDef[] = [
  {
    id: "documents_extraction",
    label: "Documents Extraction",
    icon: "📄",
    description: "Native extraction, local OCR, or cloud document AI",
  },
  {
    id: "bank_consolidation",
    label: "Bank Account Consolidation",
    icon: "🏦",
    description: "Financial table extraction & transaction reconciliation",
  },
  {
    id: "font_conversion",
    label: "Font Conversion",
    icon: "🔤",
    description: "Legacy Hindi typewriter font to/from Unicode conversion",
  },
  {
    id: "translation",
    label: "Translation",
    icon: "🌐",
    description: "Local neural or cloud translation between Hindi and English",
  },
];

export function isCloudAction(actionId: string): boolean {
  return (
    actionId.startsWith("gemini_") ||
    actionId.startsWith("azure_") ||
    actionId.startsWith("mistral_") ||
    actionId.includes("cloud")
  );
}

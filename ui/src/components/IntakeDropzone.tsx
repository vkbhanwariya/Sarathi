export interface IntakeDropzoneProps {
  working: boolean;
  hasItems: boolean;
  recursive: boolean;
  manualPath: string;
  onBrowseFiles: () => void;
  onBrowseFolder: () => void;
  onClear: () => void;
  onToggleRecursive: (recursive: boolean) => void;
  onManualPathChange: (path: string) => void;
  onAddManualPath: () => void;
}

export function IntakeDropzone({
  working,
  hasItems,
  recursive,
  manualPath,
  onBrowseFiles,
  onBrowseFolder,
  onClear,
  onToggleRecursive,
  onManualPathChange,
  onAddManualPath,
}: IntakeDropzoneProps) {
  return (
    <div class="intake-dropzone-section">
      {/* Quick Action Bar */}
      <div class="intake-actions-toolbar">
        <div class="intake-btn-group">
          <button
            id="btn-browse-files"
            class="btn-action"
            disabled={working}
            onClick={onBrowseFiles}
            type="button"
          >
            + Add files
          </button>
          <button
            id="btn-browse-folder"
            class="btn-action"
            disabled={working}
            onClick={onBrowseFolder}
            type="button"
          >
            + Add folder
          </button>
          <button
            class="btn-clear"
            disabled={working || !hasItems}
            onClick={onClear}
            type="button"
          >
            Clear
          </button>
        </div>
        <label class="recursive-label">
          <input
            type="checkbox"
            checked={recursive}
            onChange={(event) => {
              onToggleRecursive(event.currentTarget.checked);
            }}
          />
          <span>Recursive folders</span>
        </label>
      </div>

      {/* Path Input Bar */}
      <div class="path-input-bar">
        <input
          class="path-input"
          placeholder="Paste a file or folder path and press Enter"
          value={manualPath}
          onInput={(event) => onManualPathChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && manualPath.trim()) {
              onAddManualPath();
            }
          }}
        />
        <button
          class="btn-add-path"
          disabled={working || !manualPath.trim()}
          onClick={onAddManualPath}
          type="button"
        >
          Add
        </button>
      </div>

      {/* Supported Format Badges */}
      <div class="supported-formats-pills">
        <span class="format-pill">PDF</span>
        <span class="format-pill">DOCX</span>
        <span class="format-pill">XLSX</span>
        <span class="format-pill">CSV</span>
        <span class="format-pill">IMAGES</span>
      </div>
    </div>
  );
}

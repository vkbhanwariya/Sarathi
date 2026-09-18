import { useEffect, useMemo, useRef, useState } from "preact/hooks";

export function CommandPalette({
  open,
  onClose,
  commands,
}: {
  open: boolean;
  onClose: () => void;
  commands: readonly { id: string; label: string; action: () => void }[];
}) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  if (!open) return null;

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((idx) => (filtered.length ? (idx + 1) % filtered.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((idx) => (filtered.length ? (idx - 1 + filtered.length) % filtered.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const cmd = filtered[selectedIndex];
      if (cmd) {
        onClose();
        cmd.action();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <div
      class="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <dialog id="command-palette-dialog" class="palette-dialog" open aria-modal="true" aria-label="Command Palette">
        <div class="palette-content">
          <input
            ref={inputRef}
            id="palette-search-input"
            class="palette-search"
            placeholder="Type a command or jump to screen (F1-F5)..."
            autocomplete="off"
            value={query}
            onInput={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={handleKeyDown}
          />
          <div id="palette-command-list" class="palette-list">
            {filtered.length === 0 ? (
              <div class="palette-item empty">No matching commands found.</div>
            ) : (
              filtered.map((cmd, idx) => (
                <button
                  key={cmd.id}
                  class={idx === selectedIndex ? "palette-item active" : "palette-item"}
                  data-index={idx}
                  onClick={() => {
                    onClose();
                    cmd.action();
                  }}
                  type="button"
                >
                  <span>{cmd.label}</span>
                </button>
              ))
            )}
          </div>
        </div>
      </dialog>
    </div>
  );
}

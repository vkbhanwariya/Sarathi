import type { ActionParameterView, AvailableActionView } from "../types";

export function Metric({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return (
    <article class="metric">
      <span class="metric__label">{label}</span>
      <strong>{value}</strong>
      {detail ? <span class="metric__detail">{detail}</span> : null}
    </article>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div class="empty-state">
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

export function actionDefaults(action: AvailableActionView | undefined): Record<string, unknown> {
  const defaults: Record<string, unknown> = {};
  for (const parameter of action?.parameters ?? []) defaults[parameter.parameter_id] = parameter.default_value;
  return defaults;
}

export function ActionParameter({
  parameter,
  value,
  onChange,
}: {
  parameter: ActionParameterView;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const inputId = `param-${parameter.parameter_id}`;
  if (parameter.kind === "toggle") {
    return (
      <label class="toggle-row">
        <input
          id={inputId}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.currentTarget.checked)}
        />
        <span>
          <strong>{parameter.display_name}</strong>
          {parameter.description ? <small>{parameter.description}</small> : null}
        </span>
      </label>
    );
  }
  if (parameter.kind === "select") {
    return (
      <label class="field">
        <span>{parameter.display_name}</span>
        <select
          id={inputId}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.currentTarget.value)}
          onInput={(event) => onChange(event.currentTarget.value)}
        >
          {parameter.options.map(([optionValue, label]) => (
            <option value={optionValue} key={optionValue}>
              {label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <label class="field">
      <span>{parameter.display_name}</span>
      <input id={inputId} value={String(value ?? "")} onInput={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

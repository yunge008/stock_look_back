interface PercentInputProps {
  label: string;
  value: number | string;
  onChange: (value: number) => void;
  step?: number | string;
  min?: number;
  max?: number;
  hint?: string;
}

export function PercentInput({ label, value, onChange, step = 0.01, min, max, hint }: PercentInputProps) {
  return <div>
    <label>{label}</label>
    <div className="relative">
      <input
        aria-label={`${label}（百分比）`}
        className="pr-9"
        type="number"
        step={step}
        min={min}
        max={max}
        value={value}
        onChange={event => onChange(Number(event.target.value))}
      />
      <span className="suffix">%</span>
    </div>
    {hint && <p className="hint">{hint}</p>}
  </div>;
}
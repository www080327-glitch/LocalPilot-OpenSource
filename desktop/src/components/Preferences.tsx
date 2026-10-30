import { type CSSProperties, useId } from "react";
import { Cloud, ShieldCheck } from "lucide-react";
import { sources, type Preferences } from "../preferences";
function PreferenceSlider({
  title,
  options,
  value,
  onChange,
  icon,
}: {
  title: string;
  options: readonly { id: string; label: string; detail: string }[];
  value: string;
  onChange: (s: any) => void;
  icon: React.ReactNode;
}) {
  const id = useId(),
    index = Math.max(
      0,
      options.findIndex((o) => o.id === value),
    );
  return (
    <section
      className="preference-slider"
      style={
        {
          "--preference-progress": `${(index / (options.length - 1)) * 100}%`,
        } as CSSProperties
      }
    >
      <div className="preference-heading">
        <label htmlFor={id}>
          {icon}
          {title}
        </label>
        <strong>{options[index].label}</strong>
      </div>
      <div className="preference-rail">
        <div className="preference-fill" />
        <div className="preference-ticks">
          {options.map((o) => (
            <i key={o.id} />
          ))}
        </div>
        <input
          id={id}
          aria-label={title}
          aria-valuetext={options[index].label}
          type="range"
          min="0"
          max={options.length - 1}
          step="1"
          value={index}
          onChange={(e) => onChange(options[Number(e.target.value)].id)}
        />
      </div>
      <div className="preference-labels">
        {options.map((o) => (
          <button
            key={o.id}
            aria-label={`${title} ${o.label}`}
            aria-pressed={value === o.id}
            onClick={() => onChange(o.id)}
          >
            {o.label}
          </button>
        ))}
      </div>
      <p className="preference-description">{options[index].detail}</p>
    </section>
  );
}
export function PreferenceControls({
  value,
  onChange,
  supported = false,
}: {
  value: Preferences;
  onChange: (p: Preferences) => void;
  supported?: boolean;
}) {
  return (
    <div className="preference-controls">
      <PreferenceSlider
        title="模型来源"
        icon={<Cloud size={15} />}
        options={sources}
        value={value.source}
        onChange={(source) => onChange({ ...value, source })}
      />
      <p className="preference-contract">
        <ShieldCheck size={13} />
        {supported
          ? "按所选偏好选择模型；云端仍会单独询问"
          : "此服务暂不支持自动选择模型，请手动选择"}
      </p>
    </div>
  );
}

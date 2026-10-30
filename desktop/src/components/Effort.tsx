import { useId, type CSSProperties } from "react";
import { Sparkles, LockKeyhole } from "lucide-react";
export const demoEfforts = ["minimal", "low", "medium", "high", "max"];
const names: Record<string, string> = {
  none: "关闭",
  minimal: "轻量",
  low: "专注",
  medium: "深入",
  high: "深思",
  max: "极致",
  ultra: "Ultra",
  pro: "Pro",
};
export function Effort({
  options,
  value,
  onChange,
  variant = "aurora",
  preview = false,
}: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
  variant?: "aurora" | "spectrum" | "steps";
  preview?: boolean;
}) {
  const id = useId(),
    index = Math.max(0, options.indexOf(value)),
    progress = options.length > 1 ? index / (options.length - 1) : 0;
  return (
    <div
      className={`effort ${variant} ${options.length ? "" : "locked"}`}
      style={
        {
          "--effort": progress,
          "--progress": `${progress * 100}%`,
        } as CSSProperties
      }
    >
      <div className="effort-heading">
        <span>
          <Sparkles size={14} />
          思考强度
        </span>
        <span className="effort-value">
          {options.length ? (
            names[value] || value
          ) : (
            <>
              <LockKeyhole size={11} />
              由服务配置
            </>
          )}
        </span>
      </div>
      <div className="effort-rail">
        <div className="effort-halo" />
        <div className="effort-track" />
        <div className="effort-fill" />
        {options.length > 0 && (
          <div className="effort-ticks">
            {options.map((o, i) => (
              <i className={i <= index ? "lit" : ""} key={o} />
            ))}
          </div>
        )}
        <input
          id={id}
          aria-label="思考强度"
          aria-valuetext={names[value] || value || "由服务配置"}
          type="range"
          min={0}
          max={Math.max(options.length - 1, 1)}
          step={1}
          value={index}
          disabled={!options.length}
          onChange={(e) => onChange(options[Number(e.target.value)])}
        />
      </div>
      <div className="effort-labels">
        {options.length ? (
          options.map((o, i) => (
            <button
              key={o}
              className={i === index ? "selected" : ""}
              onClick={() => onChange(o)}
              aria-label={`思考强度 ${names[o] || o}`}
            >
              {names[o] || o}
            </button>
          ))
        ) : (
          <>
            <span>模型能力未声明可选档位</span>
            <span>RC2</span>
          </>
        )}
      </div>
      {preview && (
        <p className="micro muted">
          模拟能力档位 · 仅用于比较交互，不会提交模型参数
        </p>
      )}
    </div>
  );
}

import { useState } from "react";
import { Terminal, ShieldCheck, Play } from "lucide-react";
import commands from "../cli-tools.json";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";
export function SuiteTools({
  available,
  onTask,
}: {
  available: boolean;
  onTask: (t: any) => void;
}) {
  const [id, setId] = useState("doctor"),
    [values, setValues] = useState<Json>({}),
    [reviewed, setReviewed] = useState(false),
    [result, setResult] = useState<Json | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const command = commands.find((c) => c.id === id)!;
  const change = (key: string, value: unknown) => {
    setValues((v) => ({ ...v, [key]: value }));
    setReviewed(false);
    setResult(null);
  };
  return (
    <section className="suite-tools">
      <p className="micro muted">
        固定的 Suite / Companion
        命令，经原生层验证。审批与安全恢复使用任务详情的可信终端入口。模型来源偏好仅作用于会话
        Composer；此处直接调用各命令的 Host 策略。
      </p>
      <label className="field-label">
        功能
        <select
          aria-label="Suite 工具功能"
          value={id}
          onChange={(e) => {
            setId(e.target.value);
            setValues({});
            setResult(null);
            setReviewed(false);
            setError("");
          }}
        >
          {commands.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      {command.fields.map((f: any) => (
        <label className="field-label" key={f.key}>
          {f.label}
          {f.optional ? "（可选）" : ""}
          {f.type === "choice" ? (
            <select
              aria-label={f.label}
              value={values[f.key] || ""}
              onChange={(e) => change(f.key, e.target.value)}
            >
              <option value="">请选择</option>
              {f.options.map((o: string) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          ) : f.type === "boolean" ? (
            <input
              aria-label={f.label}
              type="checkbox"
              checked={!!values[f.key]}
              onChange={(e) => change(f.key, e.target.checked)}
            />
          ) : (
            <input
              aria-label={f.label}
              type={f.type === "number" ? "number" : "text"}
              min={f.min}
              max={f.max}
              value={values[f.key] ?? ""}
              onChange={(e) =>
                change(
                  f.key,
                  f.type === "number" && e.target.value !== ""
                    ? Number(e.target.value)
                    : e.target.value,
                )
              }
            />
          )}
        </label>
      ))}
      <div className="onboarding-note">
        <ShieldCheck size={17} />
        <p>{command.review}</p>
      </div>
      <p className="micro muted">
        <Terminal size={12} /> localpilot {command.command.join(" ")} ·
        参数仅通过结构化进程调用，未经 shell
      </p>
      {command.confirm && (
        <label className="tool-confirm">
          <input
            type="checkbox"
            aria-label="我已核对本次操作范围"
            checked={reviewed}
            onChange={(e) => setReviewed(e.target.checked)}
          />
          我已核对本次操作范围，确认执行
        </label>
      )}
      <button
        className="primary"
        disabled={
          busy || !desktop || !available || (command.confirm && !reviewed)
        }
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            const r = await call<Json>("suite_tool", {
              operation: id,
              values,
              confirmed: reviewed,
            });
            setResult(r);
            if (id === "task-watch" && r.exit === 0 && r.result?.[0]?.id)
              onTask(r.result[0]);
          } catch (e) {
            setError(String(e));
          } finally {
            setBusy(false);
            setReviewed(false);
          }
        }}
      >
        <Play size={13} />
        {busy ? "等待 CLI 返回…" : "执行选定操作"}
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {result && <pre className="json">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  );
}

import { useEffect, useState } from "react";
import { Folder, Terminal, Copy, ShieldCheck, Search } from "lucide-react";
import catalog from "../developer-catalog.json";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";
export default function DeveloperTools() {
  const [query, setQuery] = useState(""),
    [id, setId] = useState("agent.__main__"),
    [values, setValues] = useState<Json>({}),
    [profile, setProfile] = useState<Json | null>(null),
    [result, setResult] = useState<Json | null>(null),
    [error, setError] = useState(""),
    [copied, setCopied] = useState(false);
  const entry = catalog.entrypoints.find((e) => e.id === id)!;
  const items = catalog.entrypoints.filter((e) =>
    `${e.label} ${e.id}`.toLowerCase().includes(query.toLowerCase()),
  );
  useEffect(() => {
    if (desktop)
      call<Json>("developer_profile")
        .then(setProfile)
        .catch((e) => setError(String(e)));
  }, []);
  return (
    <div className="developer-tools">
      <div className="onboarding-note">
        <ShieldCheck size={17} />
        <p>
          历史工具可直接启动 Runtime、修改 Host
          配置或请求电脑操作权限。这里提供全部参数并生成可信终端命令；不会在
          WebView 或普通 Agent
          身份中执行。它们使用独立会话，不会让工作台偏好自动生效。
        </p>
      </div>
      <div className="developer-source">
        <span className="micro muted">
          源码目录：{profile?.source || "请选择原 LocalPilot 源码根目录"}
        </span>
        <button
          className="secondary"
          disabled={!desktop}
          onClick={async () => {
            try {
              const p = await call<Json>("pick_developer_source");
              setProfile((old) => ({ ...old, ...p }));
              setResult(null);
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          <Folder size={13} />
          选择源码目录
        </button>
      </div>
      <div className="developer-source">
        <span className="micro muted">
          Python：{profile?.python || "未选择解释器"}
        </span>
        <button
          className="secondary"
          disabled={!desktop}
          onClick={async () => {
            try {
              const p = await call<Json>("pick_developer_python");
              setProfile((old) => ({ ...old, ...p }));
              setResult(null);
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          <Folder size={13} />
          选择 Python
        </button>
      </div>
      <p className="micro muted">
        冻结契约：{catalog.source_commit.slice(0, 8)} ·{" "}
        {catalog.entrypoints.length} 个入口 · {catalog.metrics.parameter_fields}{" "}
        个参数字段。参数说明来自原 CLI，不表示能力已获授权或已实测。
      </p>
      <div className="search">
        <Search size={14} />
        <input
          aria-label="搜索开发工具"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Agent、Computer、备份、MCP、Suite…"
        />
      </div>
      <label className="field-label">
        历史与完整 CLI
        <select
          aria-label="开发工具入口"
          value={id}
          onChange={(e) => {
            setId(e.target.value);
            setValues({});
            setResult(null);
            setError("");
          }}
        >
          {!items.some((e) => e.id === id) && (
            <option value={id}>{entry.label}</option>
          )}
          {items.map((e) => (
            <option value={e.id} key={e.id}>
              {e.label}
            </option>
          ))}
        </select>
      </label>
      {entry.id === "legacy-main" && (
        <p className="micro muted">
          原 main.py
          会在可信终端依次询问优化偏好、最大上下文与模型/上下文取舍；推荐值是
          heuristic，不是测得性能或自动部署。后续进入原 Agent 交互。
        </p>
      )}
      <details className="developer-fields" open>
        <summary>完整参数（留空使用原 CLI 默认值）</summary>
        <div className="developer-form">
          {entry.fields.map((f: any) => (
            <label className="field-label" key={f.key}>
              <span>
                {f.flag || f.dest}
                {f.required && f.nargs !== "*" && f.nargs !== "?" ? " *" : ""}
              </span>
              {f.type === "boolean" ? (
                <input
                  type="checkbox"
                  aria-label={f.flag || f.dest}
                  checked={!!values[f.key]}
                  onChange={(e) => {
                    setValues((v) => ({ ...v, [f.key]: e.target.checked }));
                    setResult(null);
                  }}
                />
              ) : f.choices ? (
                <select
                  aria-label={f.flag || f.dest}
                  value={values[f.key] || ""}
                  onChange={(e) => {
                    setValues((v) => ({ ...v, [f.key]: e.target.value }));
                    setResult(null);
                  }}
                >
                  <option value="">
                    {f.default !== null
                      ? `默认：${String(f.default)}`
                      : "请选择"}
                  </option>
                  {f.choices.map((c: any) => (
                    <option key={c} value={String(c)}>
                      {String(c)}
                    </option>
                  ))}
                </select>
              ) : (
                <textarea
                  rows={
                    f.action === "append" ||
                    f.action === "raw_argv" ||
                    f.nargs === "*"
                      ? 2
                      : 1
                  }
                  aria-label={f.flag || f.dest}
                  value={values[f.key] ?? ""}
                  placeholder={
                    f.default !== null
                      ? `默认：${String(f.default)}`
                      : f.action === "append"
                        ? "每行一个值"
                        : ""
                  }
                  onChange={(e) => {
                    setValues((v) => ({ ...v, [f.key]: e.target.value }));
                    setResult(null);
                  }}
                />
              )}
              <small>
                {f.help || "原 CLI 位置参数"}
                {f.action === "append" ? "（每行一个值，可重复）" : ""}
              </small>
            </label>
          ))}
        </div>
      </details>
      <button
        className="primary"
        disabled={!desktop || !profile?.source || !profile?.python}
        onClick={async () => {
          setError("");
          setCopied(false);
          try {
            setResult(await call("developer_command", { entryId: id, values }));
          } catch (e) {
            setError(String(e));
          }
        }}
      >
        <Terminal size={14} />
        生成可信终端命令
      </button>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {result && (
        <section className="developer-result">
          <p className="micro muted">{result.notice}</p>
          <pre className="json">{result.command}</pre>
          <button
            className="secondary"
            onClick={async () => {
              await navigator.clipboard.writeText(result.command);
              setCopied(true);
            }}
          >
            <Copy size={13} />
            {copied ? "已复制，尚未执行" : "复制命令"}
          </button>
        </section>
      )}
      {(entry.module === "agent.__main__" ||
        entry.id === "legacy-main" ||
        entry.module === "computer.cli") && (
        <details className="evidence-details">
          <summary>原终端会话内的交互命令</summary>
          <p className="micro muted">
            这些命令只在上述工具已启动的交互提示符中使用，不是 shell
            命令。审批、权限与接管仍由原 CLI 检查。
          </p>
          <div className="interactive-commands">
            {(entry.module === "computer.cli"
              ? catalog.interactive_controls.computer
              : catalog.interactive_controls.agent
            ).map((command) => (
              <code key={command}>{command}</code>
            ))}
          </div>
        </details>
      )}
      {entry.module === "localpilot_service.adapter" && (
        <p className="micro muted">
          MCP stdio 使用原适配器的 initialize / ping / tools/list /
          tools/call，四个工具为
          localpilot_submit、localpilot_status、localpilot_cancel、localpilot_continue。Token
          由可信终端环境提供；继续原任务仍需要服务 operator scope。
        </p>
      )}
    </div>
  );
}

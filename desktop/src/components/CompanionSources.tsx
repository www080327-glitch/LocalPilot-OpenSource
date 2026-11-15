import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";
import type { CompanionMeeting } from "../hooks/useCompanionMeeting";
import { MeetingCapture } from "./MeetingCapture";
import { TrainingSamples } from "./TrainingSamples";

export function CompanionSources({
  onError,
  meeting,
}: {
  onError: (error: unknown) => void;
  meeting: CompanionMeeting;
}) {
  const [sources, setSources] = useState<Json[]>([]);
  const [kind, setKind] = useState("codex");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function command(command: string, args: Json = {}) {
    const result = await call<Json>("companion", { command, args });
    if (result.status === "error")
      throw Error(result.error || result.text || "Companion 操作未完成");
    return result;
  }
  async function refresh() {
    const result = await command("source_list");
    setSources(result.sources || []);
  }
  useEffect(() => {
    if (desktop) void refresh().catch(onError);
  }, []);
  async function run(action: string, args: Json = {}) {
    setBusy(true);
    try {
      const result = await command(action, args);
      const sync = result.sync || result;
      setNotice(
        action === "source_revoke"
          ? `已撤销来源并移除 ${result.removed_records || 0} 条关联记录。`
          : action === "source_set_enabled"
            ? args.enabled
              ? "已恢复该来源授权。"
              : "来源已停用，相关记忆立即停止检索。"
            : `同步状态：${sync.status} · ${sync.files || 0} 个文件 · ${sync.records || 0} 条记录`,
      );
      await refresh();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  async function connect(folder: boolean) {
    try {
      const path = await call<string | null>("pick_suite", {
        kind: folder ? "companion_folder" : "companion_file",
      });
      if (path) await run("source_connect", { kind, path, follow: true });
    } catch (error) {
      onError(error);
    }
  }
  return (
    <section className="companion-sources">
      <MeetingCapture controller={meeting} />
      <h4>Companion 已授权来源</h4>
      <p className="muted">
        选择文件或文件夹后，Companion 会持续只读同步其中支持的文本。Codex
        仅读取可见用户与助手文本；会议支持 TXT、Markdown、VTT 和
        SRT。覆盖情况以每个来源的同步记录为准。
      </p>
      <div className="button-row">
        <select
          aria-label="Companion 来源类型"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          <option value="codex">Codex 对话文件</option>
          <option value="meeting">会议文本或字幕</option>
        </select>
        <button
          className="secondary"
          disabled={!desktop || busy}
          onClick={() => void connect(false)}
        >
          选择文件并接入
        </button>
        <button
          className="secondary"
          disabled={!desktop || busy}
          onClick={() => void connect(true)}
        >
          选择文件夹并接入
        </button>
        <button
          className="secondary"
          disabled={!desktop || busy}
          onClick={() => void refresh().catch(onError)}
        >
          刷新来源
        </button>
      </div>
      {notice && <p role="status">{notice}</p>}
      {!sources.length && (
        <p className="muted">
          尚未接入文本来源。可选择已有会议文本，或在上方显式启动本机转写。
        </p>
      )}
      {sources.map((source) => (
        <details key={source.id} className="advanced-settings">
          <summary>
            {source.label || source.path} ·{" "}
            {source.enabled ? "已授权" : "已停用"} ·{" "}
            {source.last_result?.status || "尚未同步"}
          </summary>
          <p>
            <code>{source.path}</code>
          </p>
          <p className="muted">
            {source.kind === "codex" ? "Codex 可见对话" : "会议文本"} ·{" "}
            {source.follow ? "持续跟随文件变化" : "手动同步"} ·{" "}
            {source.path_kind || "来源"}
          </p>
          <div className="button-row">
            <button
              className="secondary"
              disabled={busy || !source.enabled}
              onClick={() => void run("source_sync", { source_id: source.id })}
            >
              立即同步
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void run("source_set_enabled", {
                  source_id: source.id,
                  enabled: !source.enabled,
                })
              }
            >
              {source.enabled ? "停用" : "恢复授权"}
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void run("source_revoke", { source_id: source.id })
              }
            >
              撤销并移除关联记忆
            </button>
          </div>
          <pre className="json">
            {JSON.stringify(
              {
                last_sync: source.last_sync,
                result: source.last_result,
                coverage: source.coverage,
              },
              null,
              2,
            )}
          </pre>
        </details>
      ))}
      <TrainingSamples />
    </section>
  );
}

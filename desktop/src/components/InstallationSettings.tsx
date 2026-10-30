import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";

export function InstallationSettings({
  onError,
}: {
  onError: (e: unknown) => void;
}) {
  const [diagnostic, setDiagnostic] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const inspect = async () =>
    setDiagnostic(
      await call("product_control", {
        operation: "installation_diagnostics",
        args: {},
      }),
    );
  useEffect(() => {
    if (desktop) inspect().catch(() => {});
  }, []);
  const run = async (label: string, action: () => Promise<any>) => {
    setBusy(label);
    setNotice("");
    try {
      const result = await action();
      if (result?.status === "restored") {
        location.reload();
        return;
      }
      if (result)
        setNotice(
          result.next ||
            (result.destination
              ? `备份已保存：${result.destination}`
              : result.status === "restored"
                ? "已恢复到独立目录，原安装保留。重新打开应用即可连接。"
                : "操作已完成"),
        );
      await inspect();
    } catch (e) {
      onError(e);
    } finally {
      setBusy("");
    }
  };
  return (
    <details className="advanced-settings">
      <summary>安装、服务与数据恢复</summary>
      <p className="micro muted">
        {diagnostic?.compatibility?.compatible
          ? "独立组件兼容 · API 1.0"
          : "组件兼容性尚未确认"}{" "}
        · Suite{" "}
        {diagnostic?.compatibility?.versions?.["localpilot-suite"] || "—"}
      </p>
      {(
        [
          ["core", "Core"],
          ["companion", "Companion"],
          ["omlx", "oMLX"],
        ] as const
      ).map(([module, name]) => (
        <div className="setting-row" key={module}>
          <span>
            {name}
            <small>
              {(
                {
                  ready: "已就绪",
                  running: "运行中",
                  stopped: "已停止",
                  unavailable: "未连接",
                  not_configured: "尚未配置",
                } as any
              )[diagnostic?.services?.[module]?.status] ||
                diagnostic?.services?.[module]?.status ||
                "待检测"}
            </small>
          </span>
          <div className="dialog-actions">
            {[
              ["recover", "启动 / 恢复"],
              ["stop", "停止"],
            ].map(([action, label]) => (
              <button
                className="secondary"
                key={action}
                disabled={!!busy}
                onClick={() =>
                  run(`${name} ${label}`, () =>
                    call("product_control", {
                      operation: "service_control",
                      args: { module, action, confirmed: true },
                    }),
                  )
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="dialog-actions">
        <button
          className="secondary"
          disabled={!!busy}
          onClick={() => run("检查服务", inspect)}
        >
          重新诊断
        </button>
        <button
          className="secondary"
          disabled={!!busy}
          onClick={() =>
            run("备份数据", () =>
              call("installation_backup", { restore: false }),
            )
          }
        >
          备份用户数据…
        </button>
        <button
          className="secondary"
          disabled={!!busy}
          onClick={() =>
            run("恢复数据", () =>
              call("installation_backup", { restore: true }),
            )
          }
        >
          从备份恢复…
        </button>
        <button
          className="secondary"
          disabled={!!busy || !desktop}
          onClick={() =>
            run("打开 Finder", () => call("installation_location"))
          }
        >
          显示用户数据
        </button>
        <button
          className="secondary"
          disabled={!!busy || !desktop}
          onClick={() =>
            run("停止独立组件", () =>
              call("product_control", {
                operation: "prepare_uninstall",
                args: { confirmed: true },
              }),
            )
          }
        >
          卸载前停止组件
        </button>
      </div>
      {(busy || notice) && <p role="status">{busy || notice}</p>}
      <p className="micro muted">
        备份包含历史、配置与私有密钥，请保存在受保护的位置。模型权重与工作区保留原位置。恢复会创建独立目录。卸载时先停止服务，再将应用移到废纸篓；用户数据保留。
      </p>
    </details>
  );
}

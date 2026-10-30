import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
export function WorkspaceScope({
  selected,
  onSelect,
  onError,
}: {
  selected: string;
  onSelect: (id: string) => void;
  onError: (e: unknown) => void;
}) {
  const [grants, setGrants] = useState<any[]>([]),
    [scope, setScope] = useState("organize"),
    [open, setOpen] = useState(false),
    [cloud, setCloud] = useState("");
  const refresh = () =>
    call<any>("product_control", {
      operation: "workspace_grants",
      args: { operation: "list" },
    }).then((x) => {
      setGrants(x.grants);
      if (selected && !x.grants.some((g: any) => g.id === selected && !g.revoked && g.usable !== false)) {
        onSelect("");
        onError("文件夹授权已失效，请重新选择文件夹。");
      }
    });
  useEffect(() => {
    if (desktop) refresh().catch(() => {});
    if (!desktop) return;
    const sync = () => refresh().catch(() => {});
    window.addEventListener("focus", sync);
    const timer = window.setInterval(sync, 15000);
    return () => { window.removeEventListener("focus", sync); window.clearInterval(timer); };
  }, [selected]);
  const active = grants.find((g) => g.id === selected && !g.revoked && g.usable !== false);
  return (
    <div className="workspace-scope">
      <button
        className="secondary"
        onClick={() => {
          setOpen(!open);
          refresh().catch(onError);
        }}
        title={active?.path || "当前使用服务默认工作区"}
        aria-label="授权文件夹"
      >
        {active ? `文件夹：${active.path.split("/").pop()}` : "选择文件夹"}
      </button>
      {open && (
        <section aria-label="文件夹授权设置">
          <p>
            仅授权你选择的目录。读取可查看文件；整理可建目录、移动、重命名和复制；修改还允许编辑。所有范围均关闭
            Shell。风险档位、云端披露和 macOS 系统权限分别检查。
          </p>
          <label>
            操作范围{" "}
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="read">仅读取</option>
              <option value="organize">整理文件</option>
              <option value="modify">修改文件</option>
            </select>
          </label>
          <label>
            允许向云端披露的相对路径（每行一个，可留空；“.”仅披露当前目录清单）
            <textarea
              aria-label="云端披露路径"
              value={cloud}
              onChange={(e) => setCloud(e.target.value)}
            />
          </label>
          <button
            onClick={async () => {
              try {
                const g = await call<any>("pick_workspace", {
                  scope,
                  cloudPaths: cloud
                    .split("\n")
                    .map((s) => s.trim())
                    .filter(Boolean),
                });
                if (g) {
                  await refresh();
                  onSelect(g.id);
                }
              } catch (e) {
                onError(e);
              }
            }}
          >
            选择并授权文件夹
          </button>
          <select
            aria-label="当前授权文件夹"
            value={active ? selected : ""}
            onChange={(e) => onSelect(e.target.value)}
          >
            <option value="">服务默认范围</option>
            {grants
              .filter((g) => !g.revoked && g.usable !== false)
              .map((g) => (
                <option key={g.id} value={g.id}>
                  {g.path} · {g.scope}
                </option>
              ))}
          </select>
          {active && (
            <button
              onClick={async () => {
                try {
                  await call("product_control", {
                    operation: "workspace_grants",
                    args: { operation: "revoke", grant_id: selected },
                  });
                  onSelect("");
                  await refresh();
                } catch (e) {
                  onError(e);
                }
              }}
            >
              立即撤销此授权
            </button>
          )}
          <p>
            若系统拒绝访问：在 macOS「系统设置 → 隐私与安全性 →
            文件与文件夹」为实际 LocalPilot
            执行进程授权，然后重新选择。服务会检查实际访问；选择窗口成功不代表系统授权已传递。
          </p>
        </section>
      )}
    </div>
  );
}

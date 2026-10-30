import { useEffect, useRef, useState } from "react";
import { Check, MessageCircle, RefreshCw, ShieldCheck, X } from "lucide-react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";

export const channelLabels: Record<string, string> = {
  restore_review_required: "已恢复资料 · 待人工核对",
  update_required: "组件需更新",
  not_installed: "未安装",
  not_configured: "未配置",
  stopped: "已停止",
  connecting: "正在连接",
  connected: "已连接",
  awaiting_senders: "微信已登录 · 请从手机发一句话完成连接",
  waiting_scan: "等待扫码",
  waiting_confirmation: "已扫码 · 等待手机确认",
  logged_in: "微信已登录",
  expired: "二维码已过期",
  cancelled: "已取消",
  auth_expired: "认证已失效",
  fault: "连接故障",
  UNKNOWN: "UNKNOWN · 需要人工核对",
};
type Kind = "qq" | "wechat";
export async function channelRequest(
  kind: Kind,
  action: string,
  args: Json = {},
) {
  return call<Json>("channel_control", { kind, action, args });
}
const explanations: Record<string, string> = {
  CHANNEL_CANCELLATION_UNKNOWN_QUERY_ORIGINAL_NO_RETRY:
    "取消结果为 UNKNOWN，不能再次发送。请查询原任务及收据；此前审批的不确定性继续保留。",
  CHANNEL_UNKNOWN_NEVER_AUTOMATICALLY_CLEARED:
    "仍有待核对的结果，不能通过更换账号解除。请先核对原任务和收据。",
  CHANNEL_STOP_BEFORE_CREDENTIAL_CHANGE:
    "请先停止当前平台连接，再更换凭据。现有账号和历史保持不变。",
  CHANNEL_DECISION_REFUSED_REFRESH_IDENTITY_AND_ACTION:
    "宿主审批未被接受。请重新查询当前动作并检查连接身份，未自动重试。",
  CHANNEL_CANCELLATION_REFUSED_REFRESH_IDENTITY:
    "取消请求未被接受。请检查当前身份和任务，原记录保留。",
  CHANNEL_DECISION_UNKNOWN_QUERY_ORIGINAL_NO_RETRY:
    "审批结果未确认，未自动重试。请查询原任务及收据，保留 UNKNOWN。",
  CHANNEL_APPROVAL_CHANGED_EXPIRED_OR_PREVIEW_UNAVAILABLE:
    "审批内容已变化、过期或无法完整展示。请重新查询并核对，未执行批准。",
  CHANNEL_RESTORED_DATA_REVIEW_REQUIRED:
    "渠道资料已恢复并保持隔离。请先核对 Core 和历史，再选择恢复资料审核；不会启动旧进程或重发任务。",
  CHANNEL_COMPONENT_UPDATE_REQUIRED:
    "渠道组件需要更新才能安全使用。请使用此面板内的更新按钮，历史与配置保留。",
  CHANNEL_CLOUD_REQUIRES_EXPLICIT_HOST_CONFIRMATION:
    "云端模型需要单独选择并确认；每次任务仍需宿主出站授权。",
  CHANNEL_WORKSPACE_OVERLAPS_PRIVATE_STATE:
    "这个文件夹包含 LocalPilot 私有数据。请选择独立的任务文件夹。",
  CHANNEL_NODE_TLS_VERIFICATION_FAILED:
    "下载来源的证书验证失败，未安装或执行。请检查网络和系统时间后重试。",
  CHANNEL_UNKNOWN_REQUIRES_MANUAL_RECONCILIATION_NO_RESTART:
    "存在待核对的任务或投递结果。请查询原任务并核对收据，系统不会自动重启或重新投递。",
  CORE_ACTIVE_APPROVAL_OR_UNKNOWN_REQUIRES_MANUAL_REVIEW:
    "Core 中仍有活动任务、审批或未知结果。请先在 Agent 中处理，再重试配置。",
  CHANNEL_NODE_DOWNLOAD_INTERRUPTED_RETRY_SAFE:
    "下载中断。已保留下载进度，可重新安装继续校验。",
  CHANNEL_NODE_INSUFFICIENT_DISK:
    "磁盘空间不足，请先保留至少 512 MB 可用空间。",
  CHANNEL_EXISTING_BINDING_PRESERVED_DISCONNECT_BEFORE_RECONFIGURE:
    "当前授权已保留。更改发送者或权限前，请先断开本机连接，再建立新的绑定。",
};
export function ChannelSettings({
  onError,
  onboarding = false,
}: {
  onError: (e: unknown) => void;
  onboarding?: boolean;
}) {
  const [quickConnect, setQuickConnect] = useState(false);
  const quickPhase = useRef("");
  const [quickStep, setQuickStep] = useState("");
  const [waitSeconds, setWaitSeconds] = useState(0);
  function phase(value: string) {
    quickPhase.current = value;
    setQuickStep(value);
    setWaitSeconds(0);
  }
  useEffect(() => {
    if (!quickConnect || !quickStep) return;
    const timer = setInterval(() => setWaitSeconds((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, [quickConnect, quickStep]);
  const baselinePeers = useRef<string[]>([]);
  const [states, setStates] = useState<Record<string, Json>>({});
  const [selected, setSelected] = useState<Kind | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [senders, setSenders] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [write, setWrite] = useState(false);
  const [operator, setOperator] = useState(false);
  const [operatorSenders, setOperatorSenders] = useState<string[]>([]);
  const [allowCloud, setAllowCloud] = useState(false);
  const [reviewed, setReviewed] = useState<string[]>([]);
  const [qr, setQr] = useState("");
  const [diagnostic, setDiagnostic] = useState<Json | null>(null);
  const pending = useRef(false);
  const revision = useRef(0);
  const loginActive = useRef(false);
  async function refresh() {
    if (!desktop || pending.current) return;
    pending.current = true;
    const observedRevision = revision.current;
    try {
      const rows = await Promise.all(
        (["qq", "wechat"] as Kind[]).map(async (kind) => {
          try {
            return [
              kind,
              await channelRequest(
                kind,
                selected === kind ? "login_status" : "status",
              ),
            ] as const;
          } catch {
            return [
              kind,
              { kind, status: "UNKNOWN", connected: false },
            ] as const;
          }
        }),
      );
      const next = Object.fromEntries(rows);
      if (observedRevision !== revision.current) return;
      loginActive.current =
        !!selected &&
        ["waiting_scan", "waiting_confirmation"].includes(
          next[selected]?.status,
        );
      setStates(next);
      setQr(selected ? next[selected]?.qr_image || "" : "");
    } finally {
      pending.current = false;
    }
  }
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 3500);
    return () => {
      clearInterval(timer);
      revision.current++;
      if (selected && loginActive.current) {
        loginActive.current = false;
        void channelRequest(selected, "cancel_login").catch(() => {});
      }
    };
  }, [selected]);
  async function perform(
    kind: Kind,
    action: string,
    args: Json = {},
    success = "",
  ) {
    revision.current++;
    setBusy(action);
    setNotice("");
    try {
      const result = await channelRequest(kind, action, args);
      if (["diagnose", "receipts", "history"].includes(action))
        setDiagnostic(result);
      if (["decision", "cancel_task"].includes(action))
        setDiagnostic(await channelRequest(kind, "receipts"));
      if (result.status === "cancelled")
        setNotice("已取消，现有初始化和任务保持不变。");
      else if (success) setNotice(success);
      await refresh();
      return result;
    } catch (error) {
      const code = String(error).split("：").at(-1) || "";
      setNotice(
        explanations[code] ||
          "操作未完成，已保留配置和任务。请查看诊断；可停止后安全重试。",
      );
      onError(error);
    } finally {
      setBusy("");
    }
  }
  async function close() {
    const kind = selected;
    setQr("");
    if (
      kind &&
      ["waiting_scan", "waiting_confirmation"].includes(states[kind]?.status)
    ) {
      await perform(kind, "cancel_login");
    }
    setSelected(null);
    setDiagnostic(null);
  }
  async function connectWechat() {
    setSelected("wechat");
    setQuickConnect(true);
    phase("preparing");
    baselinePeers.current = (states.wechat?.senders || []).map(
      (s: Json) => s.id,
    );
    if (!states.wechat?.installed || states.wechat?.update_required) {
      if (
        !(await perform(
          "wechat",
          states.wechat?.update_required ? "update" : "install",
          { confirmed: true },
        ))
      ) {
        phase("");
        return;
      }
    }
    // An existing bridge must be stopped before requesting a new QR.
    // Stop is explicit here as part of the user's reconnect action.
    if (states.wechat?.processes?.wechat) {
      if (!(await perform("wechat", "stop", { confirmed: true }))) {
        phase("");
        return;
      }
    }
    if (states.wechat?.account) {
      const resumed = await perform(
        "wechat",
        states.wechat.configured ? "start" : "discover",
        { confirmed: true },
        "已恢复消息接收，正在检查连接。",
      );
      phase(
        resumed
          ? states.wechat.configured
            ? "checking"
            : "discovery"
          : "failed",
      );
      return;
    }
    const result = await perform("wechat", "login", { confirmed: true });
    phase(result ? "login" : "failed");
  }
  useEffect(() => {
    const current = states.wechat;
    if (!quickConnect || busy || !current || current.status === "UNKNOWN")
      return;
    if (
      quickPhase.current === "login" &&
      ["logged_in", "awaiting_senders"].includes(current.status)
    ) {
      phase("starting");
      void (async () => {
        if (
          current.processes?.wechat &&
          !(await perform("wechat", "stop", { confirmed: true }))
        ) {
          phase("failed");
          return;
        }
        if (current.configured) {
          await perform(
            "wechat",
            "start",
            { confirmed: true },
            "正在连接微信。",
          );
          phase("");
          return;
        }
        const discovered = await perform(
          "wechat",
          "discover",
          { confirmed: true },
          "微信已登录，正在接收消息。",
        );
        phase(discovered ? "discovery" : "failed");
      })();
    }
    if (
      ["discovery", "checking"].includes(quickStep) &&
      !current.processes?.wechat &&
      ["stopped", "cancelled", "fault", "auth_expired"].includes(current.status)
    ) {
      phase("failed");
      setNotice(
        "微信接收进程已停止，尚未连接成功。点击继续连接；无需重复扫码。",
      );
      return;
    }
    const candidates = (current.senders || []).filter(
      (s: Json) => !baselinePeers.current.includes(s.id),
    );
    const route = current.models?.find((m: Json) => m.id === model);
    if (
      quickPhase.current === "discovery" &&
      candidates.length === 1 &&
      route &&
      (!route.cloud || allowCloud)
    ) {
      phase("binding");
      void (async () => {
        const result = await perform("wechat", "configure", {
          senders: [candidates[0].id],
          model,
          allow_write: false,
          allow_cloud: !!route.cloud,
          confirmed: true,
        });
        const started =
          result &&
          (await perform(
            "wechat",
            "start",
            { confirmed: true },
            "连接已启动，正在检查状态。",
          ));
        phase(started ? "checking" : "failed");
      })();
    }
  }, [states, quickConnect, busy, model, allowCloud, quickStep]);
  useEffect(() => {
    if (!model && states.wechat?.models?.length) {
      const routes = states.wechat.models;
      setModel(
        (
          routes.find((m: Json) => m.ready && !m.cloud) ||
          routes.find((m: Json) => m.ready) ||
          routes[0]
        ).id,
      );
    }
  }, [states, model]);
  const state = selected ? states[selected] : null;
  return (
    <section className="channel-settings" aria-label="消息渠道">
      <div className="channel-heading">
        <div>
          <h3>连接消息平台</h3>
          <p className="muted">
            从手机向同一个 LocalPilot Agent
            提交任务。平台连接可随时跳过，之后在设置中继续。
          </p>
        </div>
        <button
          className="icon-btn"
          aria-label="刷新消息渠道状态"
          onClick={() => void refresh()}
        >
          <RefreshCw size={15} />
        </button>
      </div>
      <div className="wechat-quick">
        <h4>微信扫码连接（可跳过）</h4>
        <p>扫码并在手机确认。登录后发一句话，自动完成连接，无需勾选身份。</p>
        <label>
          使用模型{" "}
          <select
            aria-label="微信使用模型"
            value={model}
            onChange={(e) => {
              setModel(e.target.value);
              setAllowCloud(false);
            }}
          >
            <option value="">稍后选择模型</option>
            {states.wechat?.models?.map((m: Json) => (
              <option key={m.id} value={m.id}>
                {m.name}
                {m.cloud ? " · 云端" : " · 本地"}
              </option>
            ))}
          </select>
        </label>
        {states.wechat?.models?.find((m: Json) => m.id === model)?.cloud && (
          <label className="simple-toggle">
            <input
              type="checkbox"
              checked={allowCloud}
              onChange={(e) => setAllowCloud(e.target.checked)}
            />
            使用此云端模型（任务发送前仍需授权）
          </label>
        )}
        <button
          className="primary"
          disabled={!desktop || !!busy}
          onClick={() => void connectWechat()}
        >
          {busy
            ? "正在准备…"
            : states.wechat?.connected
              ? "重新扫码"
              : states.wechat?.account
                ? "继续连接微信"
                : "扫码连接微信"}
        </button>
        {qr && selected === "wechat" && (
          <img className="channel-qr" src={qr} alt="微信登录二维码" />
        )}
        <div
          className={`wechat-feedback ${states.wechat?.connected ? "connected" : ""}`}
          role="status"
          aria-live="polite"
        >
          <strong>
            {states.wechat?.connected
              ? "✓ 微信已连接，可以从手机提交任务"
              : "尚未连接完成"}
          </strong>
          <p>
            {states.wechat?.connected
              ? "平台登录、身份绑定与服务检查均已完成。"
              : quickStep === "failed"
                ? "连接中断，请查看下方原因。没有自动重发消息。"
                : quickStep === "binding"
                  ? "已收到手机消息，正在绑定身份…"
                  : quickStep === "starting"
                    ? "已登录，正在启动消息接收…"
                    : quickStep === "checking"
                      ? "已绑定身份，正在检查服务连接…"
                      : quickStep === "discovery"
                        ? `扫码登录已完成；等待收到手机消息（${waitSeconds} 秒）。`
                        : channelLabels[states.wechat?.status] ||
                          "点击上方按钮获取二维码"}
          </p>
          {quickStep === "discovery" && waitSeconds >= 30 && (
            <p>
              仍未收到消息，请确认发给本次扫码登录的机器人。若已经发送，可点“检查连接”；不需要重新扫码。
            </p>
          )}
          {quickStep === "discovery" && !model && (
            <p>请选择一个模型，收到消息后才能完成绑定。</p>
          )}
          {quickStep === "discovery" &&
            states.wechat?.models?.find((m: Json) => m.id === model)?.cloud &&
            !allowCloud && (
              <p>已选择云端模型，请勾选上方“使用此云端模型”后继续绑定。</p>
            )}
          {quickConnect && !states.wechat?.connected && (
            <button
              className="secondary"
              disabled={!!busy}
              onClick={() => void refresh()}
            >
              检查连接
            </button>
          )}
        </div>
        {quickConnect && (
          <button
            className="text-btn"
            onClick={() => {
              setQuickConnect(false);
              phase("");
              void close();
            }}
          >
            取消连接
          </button>
        )}
        {quickConnect && quickStep === "discovery" && (
          <p>
            请从手机给机器人发一句话。发现一个新身份后将自动连接；文件修改等权限可稍后设置。
          </p>
        )}
        {quickConnect &&
          states.wechat?.senders?.filter(
            (s: Json) => !baselinePeers.current.includes(s.id),
          ).length > 1 && (
            <p>发现多个新身份，请展开高级设置选择要连接的身份。</p>
          )}
      </div>
      <details className="advanced-settings">
        <summary>高级 · QQ、权限与连接诊断</summary>
        <div className="channel-grid">
          {(["qq", "wechat"] as Kind[]).map((kind) => {
            const value = states[kind];
            return (
              <article className="channel-card" key={kind}>
                <div className={`channel-icon ${kind}`} aria-hidden="true">
                  <MessageCircle size={25} />
                  <span>{kind === "qq" ? "Q" : "微"}</span>
                </div>
                <div>
                  <h4>{kind === "qq" ? "QQ" : "微信"}</h4>
                  <p className="micro muted">
                    {kind === "qq"
                      ? "官方机器人私聊文本 · 需创建机器人"
                      : "iLink 扫码登录 · 需手机确认"}
                  </p>
                </div>
                <span
                  className={`channel-state ${value?.connected ? "ready" : ""}`}
                  role="status"
                >
                  {channelLabels[value?.status] ||
                    (desktop ? "正在检测" : "原生应用中可连接")}
                </span>
                <button
                  className="secondary"
                  disabled={!desktop || !!busy}
                  onClick={() => {
                    setSelected(kind);
                    setSenders([]);
                    setModel("");
                    setWrite(false);
                    setOperator(false);
                    setOperatorSenders([]);
                    setReviewed([]);
                    setAllowCloud(false);
                    setNotice("");
                    setDiagnostic(null);
                  }}
                >
                  {value?.configured ? "管理连接" : "连接"}
                </button>
                {onboarding && (
                  <button
                    className="text-btn"
                    disabled={!desktop || !!busy}
                    onClick={() =>
                      void perform(
                        kind,
                        "skip",
                        {},
                        "已选择稍后设置，标准 Agent 可独立使用。",
                      )
                    }
                  >
                    稍后设置
                  </button>
                )}
              </article>
            );
          })}
        </div>
        {selected && (
          <div
            className="channel-panel"
            role="region"
            aria-label={`${selected === "qq" ? "QQ" : "微信"}连接引导`}
          >
            <div className="channel-heading">
              <h4>{selected === "qq" ? "连接 QQ 机器人" : "连接微信"}</h4>
              <button
                className="icon-btn"
                aria-label="关闭渠道引导"
                disabled={!!busy}
                onClick={() => void close()}
              >
                <X size={16} />
              </button>
            </div>
            <p className="micro muted">
              手动连接和权限管理。普通用户可使用上方扫码连接。
            </p>
            {state?.restored_data && (
              <div className="channel-step">
                <p>
                  已恢复的渠道资料处于隔离状态，尚未连接。先在安装与服务中准备恢复后的
                  Core，并核对历史。审核只建立新的连接入口，不启动旧进程或重发任务。
                </p>
                <button
                  className="secondary"
                  disabled={!!busy}
                  onClick={() =>
                    void perform(
                      selected,
                      "restore_review",
                      { confirmed: true },
                      "恢复资料已核对。历史保留，请重新确认平台身份和发送者。",
                    )
                  }
                >
                  核对恢复资料，重新设置连接
                </button>
              </div>
            )}
            {!state?.restored_data &&
              (!state?.installed || state?.update_required) && (
                <div className="channel-step">
                  <strong>1 · 安装可选组件</strong>
                  <p>
                    如未准备，将下载并校验 Node.js {"22.23.4"}（约 50
                    MB），并安装 APP
                    内已校验的渠道组件。已缓存的资源会复核后复用，无需终端或已有
                    Python / Node。
                  </p>
                  <button
                    className="primary"
                    disabled={!!busy}
                    onClick={() =>
                      void perform(
                        selected,
                        state?.update_required ? "update" : "install",
                        { confirmed: true },
                        "可选组件已安装；尚未连接平台。",
                      )
                    }
                  >
                    {busy === "install"
                      ? "正在下载、校验并安装…"
                      : "同意下载并安装渠道组件"}
                  </button>
                  {busy === "install" && (
                    <button
                      className="text-btn"
                      onClick={() =>
                        void channelRequest(selected, "cancel_download")
                      }
                    >
                      取消下载
                    </button>
                  )}
                </div>
              )}
            {state?.installed &&
              !state?.update_required &&
              !state?.configured && (
                <>
                  <div className="channel-step">
                    <strong>
                      2 ·{" "}
                      {selected === "qq" ? "官方机器人认证" : "手机扫码登录"}
                    </strong>
                    {selected === "qq" ? (
                      <>
                        <button
                          className="secondary"
                          disabled={!!busy}
                          onClick={() => void perform("qq", "qq_console")}
                        >
                          打开 QQ 官方机器人平台
                        </button>
                        <p>
                          先在 QQ 官方平台创建机器人，在开发管理中获取 AppID 和
                          AppSecret，完成平台要求的发布或沙箱授权。当前支持机器人私聊文本；群聊、频道、好友聊天记录和审批命令不在接入范围内。
                        </p>
                        <button
                          className="secondary"
                          disabled={!!busy}
                          onClick={() =>
                            void perform(
                              "qq",
                              "qq_credentials",
                              {},
                              "凭据已通过原生输入保存。请继续连接机器人。",
                            )
                          }
                        >
                          安全输入 AppID 与 AppSecret…
                        </button>
                        <button
                          className="secondary"
                          disabled={!!busy || state?.status === "UNKNOWN"}
                          onClick={() =>
                            void perform(
                              "qq",
                              "discover",
                              { confirmed: true },
                              "请用要授权的 QQ 身份向机器人发送“连接测试”。此时只识别发送者，不执行任务。",
                            )
                          }
                        >
                          连接机器人并识别发送者
                        </button>
                      </>
                    ) : (
                      <>
                        <p>
                          二维码仅在本机临时显示。用手机微信扫码并确认；取消或过期后可重新获取，历史任务不会重新投递。
                        </p>
                        <button
                          className="secondary"
                          disabled={
                            !!busy ||
                            state?.processes?.wechat ||
                            state?.status === "UNKNOWN"
                          }
                          onClick={() =>
                            void perform("wechat", "login", { confirmed: true })
                          }
                        >
                          获取微信登录二维码
                        </button>
                        {qr && (
                          <img
                            className="channel-qr"
                            src={qr}
                            alt="微信平台登录二维码，请用手机扫码并确认"
                          />
                        )}
                        <p role="status">
                          {channelLabels[state?.status] || "等待获取二维码"}
                        </p>
                        {[
                          "waiting_scan",
                          "waiting_confirmation",
                          "connecting",
                        ].includes(state?.status) && (
                          <button
                            className="text-btn"
                            disabled={!!busy}
                            onClick={() => {
                              setQr("");
                              void perform("wechat", "cancel_login");
                            }}
                          >
                            取消扫码
                          </button>
                        )}
                        <button
                          className="secondary"
                          disabled={
                            !!busy ||
                            state?.processes?.wechat ||
                            state?.status === "UNKNOWN"
                          }
                          onClick={() =>
                            void perform(
                              "wechat",
                              "discover",
                              { confirmed: true },
                              "请从要授权的微信身份发送“连接测试”。未授权消息只用于识别发送者。",
                            )
                          }
                        >
                          登录后识别发送者
                        </button>
                      </>
                    )}
                  </div>
                  <div className="channel-step">
                    <strong>3 · 确认发送者与权限</strong>
                    <p>
                      先从手机发一条连接测试消息，再勾选你本人确认的发送者。界面仅显示脱敏身份。
                    </p>
                    {state?.senders?.map((sender: Json) => (
                      <label className="simple-toggle" key={sender.id}>
                        <input
                          type="checkbox"
                          checked={senders.includes(sender.id)}
                          onChange={(e) =>
                            setSenders(
                              e.target.checked
                                ? [...senders, sender.id]
                                : senders.filter((s) => s !== sender.id),
                            )
                          }
                        />
                        {sender.label}
                      </label>
                    ))}
                    {!state?.senders?.length && (
                      <p className="muted">尚未发现发送者。</p>
                    )}
                    <label>
                      Agent 模型
                      <select
                        aria-label="渠道 Agent 模型"
                        value={model}
                        onChange={(e) => {
                          setModel(e.target.value);
                          setAllowCloud(false);
                        }}
                      >
                        <option value="">请选择已配置的 Agent 模型</option>
                        {state?.models?.map((m: Json) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                            {m.cloud ? " · 云端，逐次宿主授权" : " · 本地"}
                            {m.ready ? "" : " · 尚未就绪"}
                          </option>
                        ))}
                      </select>
                    </label>
                    {state?.models?.find((m: Json) => m.id === model)
                      ?.cloud && (
                      <label className="simple-toggle">
                        <input
                          type="checkbox"
                          checked={allowCloud}
                          onChange={(e) => setAllowCloud(e.target.checked)}
                        />
                        明确选择此云端模型；每条任务需宿主授权，本地文件出站还需额外确认
                      </label>
                    )}
                    <p className="micro muted">
                      默认仅能读取独立渠道工作区。也可在本机选择此渠道可访问的文件夹。Shell、云端、Computer
                      Use 和自我审批关闭。
                    </p>
                    <p className="micro">
                      当前工作区：
                      {state?.permissions?.workspace || "独立渠道工作区"}
                    </p>
                    <button
                      className="secondary"
                      disabled={!!busy}
                      onClick={() =>
                        void perform(
                          selected,
                          "workspace",
                          {},
                          "工作文件夹已暂存，确认发送者后才会建立 Core 绑定。",
                        )
                      }
                    >
                      选择渠道工作文件夹…
                    </button>
                    <label className="simple-toggle">
                      <input
                        type="checkbox"
                        checked={write}
                        onChange={(e) => setWrite(e.target.checked)}
                      />
                      允许在已选择的渠道工作区请求文件修改，每次修改需宿主审批
                    </label>
                    {selected === "wechat" && (
                      <details>
                        <summary>高级 · 独立微信审批身份</summary>
                        <p>
                          普通消息身份不会获得审批能力。另建仅可审批所选发送者自身任务的
                          Operator，下面单独选择哪些发送者可使用微信审批命令；不能代批其他发送者的任务。
                        </p>
                        <label className="simple-toggle">
                          <input
                            type="checkbox"
                            checked={operator}
                            onChange={(e) => setOperator(e.target.checked)}
                          />
                          开启独立微信审批身份
                        </label>
                        {operator &&
                          state?.senders
                            ?.filter((s: Json) => senders.includes(s.id))
                            .map((s: Json) => (
                              <label className="simple-toggle" key={s.id}>
                                <input
                                  type="checkbox"
                                  checked={operatorSenders.includes(s.id)}
                                  onChange={(e) =>
                                    setOperatorSenders(
                                      e.target.checked
                                        ? [...operatorSenders, s.id]
                                        : operatorSenders.filter(
                                            (id) => id !== s.id,
                                          ),
                                    )
                                  }
                                />
                                {s.label} · 仅审批其自身任务
                              </label>
                            ))}
                      </details>
                    )}
                    <button
                      className="primary"
                      disabled={
                        !!busy ||
                        !senders.length ||
                        !model ||
                        (operator && !operatorSenders.length) ||
                        (state?.models?.find((m: Json) => m.id === model)
                          ?.cloud &&
                          !allowCloud)
                      }
                      onClick={async () => {
                        if (
                          selected === "wechat" &&
                          !(await perform(selected, "operator", {
                            senders: operatorSenders.filter((id) =>
                              senders.includes(id),
                            ),
                            enabled: operator,
                            confirmed: true,
                          }))
                        )
                          return;
                        if (
                          await perform(
                            selected,
                            "configure",
                            {
                              senders,
                              model,
                              allow_write: write,
                              allow_cloud: allowCloud,
                              confirmed: true,
                            },
                            "Core 普通身份已建立。请启动并核验实际连接。",
                          )
                        )
                          setQr("");
                      }}
                    >
                      确认授权并创建最小权限绑定
                    </button>
                  </div>
                </>
              )}
            {state?.configured && (
              <div className="channel-step">
                <strong>连接管理</strong>
                <p>
                  {channelLabels[state.status] || "状态未知"} · 账号{" "}
                  {state.account || "未确认"} · 发送者授权已独立保存
                </p>
                <button
                  className="primary"
                  disabled={
                    !!busy ||
                    state.processes?.[selected] ||
                    state.status === "UNKNOWN"
                  }
                  onClick={() =>
                    void perform(selected, "start", { confirmed: true })
                  }
                >
                  启动并核验连接
                </button>
                <button
                  className="secondary"
                  disabled={!!busy}
                  onClick={() =>
                    void perform(selected, "stop", { confirmed: true })
                  }
                >
                  停止
                </button>
                <button
                  className="secondary"
                  disabled={!!busy}
                  onClick={() => void perform(selected, "diagnose")}
                >
                  测试连接
                </button>
                {selected === "wechat" && (
                  <button
                    className="secondary"
                    disabled={
                      !!busy ||
                      state.processes?.wechat ||
                      state.status === "UNKNOWN"
                    }
                    onClick={() =>
                      void perform("wechat", "login", { confirmed: true })
                    }
                  >
                    重新扫码登录
                  </button>
                )}
                {qr && (
                  <img
                    className="channel-qr"
                    src={qr}
                    alt="微信平台重新登录二维码"
                  />
                )}
                <label className="simple-toggle">
                  <input
                    type="checkbox"
                    checked={state.background === true}
                    disabled={!!busy}
                    onChange={(e) =>
                      void perform(selected, "background", {
                        enabled: e.target.checked,
                        confirmed: true,
                      })
                    }
                  />
                  退出 Desktop 后继续保持渠道运行
                </label>
                <p className="micro muted">
                  默认退出时停止本机渠道；下次打开不会自动连接或恢复危险任务。
                </p>
                <details>
                  <summary>安全设置与断开</summary>
                  <p>
                    普通身份：无审批权限 · 文件修改需审批 · Shell / Computer Use
                    关闭。云端
                    {state.permissions?.cloud ? "逐次由宿主授权" : "关闭"}
                    。更改发送者和权限需先断开，再建立新绑定；历史状态保留。
                  </p>
                  <button
                    className="secondary"
                    disabled={!!busy}
                    onClick={() =>
                      void perform(
                        selected,
                        "disconnect",
                        { confirmed: true },
                        "已停止并撤销本机 Core 身份。平台登录资料和历史 UNKNOWN 已保留。",
                      )
                    }
                  >
                    断开连接并撤销本机任务授权
                  </button>
                </details>
              </div>
            )}
            <details className="channel-step">
              <summary>高级诊断与只读任务收据</summary>
              <p>
                连接成功仅表示认证与服务链路就绪。工具收据和独立 Verification
                分别核对；UNKNOWN 不会自动解除。
              </p>
              <button
                className="secondary"
                disabled={!!busy}
                onClick={() => void perform(selected, "diagnose")}
              >
                诊断
              </button>
              <button
                className="secondary"
                disabled={
                  !!busy || (!state?.configured && !state?.restored_data)
                }
                onClick={() => void perform(selected, "receipts")}
              >
                查询原任务与收据
              </button>
              <button
                className="text-btn"
                disabled={!!busy}
                onClick={() =>
                  void perform(
                    selected,
                    "uninstall",
                    { confirmed: true },
                    "渠道运行代码已卸载；所有配置、登录资料、任务与共享 Node 运行时保留。",
                  )
                }
              >
                卸载已停止的渠道运行组件
              </button>
              <button
                className="text-btn"
                disabled={!!busy}
                onClick={() =>
                  void perform(selected, "rollback", { confirmed: true })
                }
              >
                恢复最近一次身份配置备份
              </button>
              <button
                className="secondary"
                disabled={!!busy}
                onClick={() =>
                  void perform(
                    selected,
                    "stop",
                    { confirmed: true },
                    "已停止此平台所有归属可确认的本机渠道进程；Core 与历史保留。",
                  )
                }
              >
                停止已确认的渠道进程
              </button>
              {!state?.configured && (
                <details>
                  <summary>安全新建连接</summary>
                  <p>
                    旧 UNKNOWN、任务和回执保留。仅在 Core
                    已停止执行且没有未核对副作用时，隔离旧连接并重新授权；旧消息不会重新投递。
                  </p>
                  <button
                    className="secondary"
                    disabled={!!busy}
                    onClick={() =>
                      void perform(
                        selected,
                        "fresh",
                        { confirmed: true },
                        "已准备新的连接入口，旧历史保留且不重发。请重新确认平台身份与发送者。",
                      )
                    }
                  >
                    保留历史，准备新连接
                  </button>
                </details>
              )}
              {state?.history?.map((item: Json) => (
                <button
                  className="text-btn"
                  key={item.generation}
                  disabled={!!busy}
                  onClick={() =>
                    void perform(selected, "history", {
                      generation: item.generation,
                    })
                  }
                >
                  {item.label}
                </button>
              ))}
              {diagnostic?.tasks?.map((task: Json) => (
                <article
                  className="channel-step"
                  key={task.official_task_id || Math.random()}
                >
                  <strong>
                    {task.official_task_id || "未确认任务"} · {task.status}
                  </strong>
                  <p className="micro muted">
                    事实来源：官方 Core · 本地映射{" "}
                    {task.local_mapping_status || "未知"} · 不自动重投
                  </p>
                  {task.required_action &&
                    Object.keys(task.required_action).length > 0 && (
                      <details>
                        <summary>核对待审批动作</summary>
                        <pre className="channel-diagnostic">
                          {JSON.stringify(task.required_action, null, 2)}
                        </pre>
                        {task.can_approve && (
                          <label className="simple-toggle">
                            <input
                              type="checkbox"
                              checked={reviewed.includes(
                                task.official_task_id +
                                  ":" +
                                  task.preview_fingerprint,
                              )}
                              onChange={(e) => {
                                const key =
                                  task.official_task_id +
                                  ":" +
                                  task.preview_fingerprint;
                                setReviewed(
                                  e.target.checked
                                    ? [...reviewed, key]
                                    : reviewed.filter((item) => item !== key),
                                );
                              }}
                            />
                            我已核对此动作的范围和副作用
                          </label>
                        )}
                      </details>
                    )}
                  {(task.preview_truncated || task.preview_redacted) && (
                    <p>
                      动作无法完整安全展示，禁止批准；可以拒绝或缩小任务后重新提交。
                    </p>
                  )}
                  {task.host_decision_unknown && (
                    <p>上次审批结果为 UNKNOWN，未自动重试。请核对原任务。</p>
                  )}
                  <div className="dialog-actions">
                    {task.can_approve && (
                      <button
                        className="secondary"
                        disabled={
                          !!busy ||
                          !reviewed.includes(
                            task.official_task_id +
                              ":" +
                              task.preview_fingerprint,
                          )
                        }
                        onClick={() =>
                          void perform(
                            selected,
                            "decision",
                            {
                              task_id: task.official_task_id,
                              approval_id: task.approval_id,
                              preview_fingerprint: task.preview_fingerprint,
                              decision_id: crypto.randomUUID(),
                              decision: "approve",
                              confirmed: true,
                            },
                            "审批请求已提交，请查询原任务收据；这不代表工具验证通过。",
                          )
                        }
                      >
                        宿主批准此动作
                      </button>
                    )}
                    {task.can_cancel && (
                      <button
                        className="text-btn"
                        disabled={!!busy}
                        onClick={() =>
                          void perform(
                            selected,
                            "cancel_task",
                            { task_id: task.official_task_id, confirmed: true },
                            "取消请求已提交。原有 UNKNOWN 和收据保留，不能据此认定此前没有副作用。",
                          )
                        }
                      >
                        请求取消原任务
                      </button>
                    )}
                    {task.can_reject && (
                      <button
                        className="secondary"
                        disabled={!!busy}
                        onClick={() =>
                          void perform(
                            selected,
                            "decision",
                            {
                              task_id: task.official_task_id,
                              approval_id: task.approval_id,
                              preview_fingerprint: task.preview_fingerprint,
                              decision_id: crypto.randomUUID(),
                              decision: "reject",
                              confirmed: true,
                            },
                            "拒绝请求已提交，请核对原任务。",
                          )
                        }
                      >
                        宿主拒绝此动作
                      </button>
                    )}
                  </div>
                </article>
              ))}
              <button
                className="text-btn"
                disabled={!!busy}
                onClick={() => void perform(selected, "logs")}
              >
                在 Finder 中查看运行记录
              </button>
              {diagnostic && (
                <pre className="channel-diagnostic">
                  {JSON.stringify(diagnostic, null, 2)}
                </pre>
              )}
            </details>
          </div>
        )}
      </details>
      {busy && (
        <p className="micro" role="status">
          正在处理，请稍候…
        </p>
      )}
      {notice && (
        <p className="setup-status" role="status">
          <Check size={14} />
          {notice}
        </p>
      )}
      <p className="micro muted">
        <ShieldCheck size={14} /> 默认不连接、不扫码、不读取通讯录。QQ
        与微信通过独立 Bridge、Adapter 连接同一个官方 Core。
      </p>
    </section>
  );
}

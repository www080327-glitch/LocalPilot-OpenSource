import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp,
  Copy,
  Settings,
  X,
  ChevronLeft,
  ExternalLink,
  RotateCcw,
} from "lucide-react";
import { call } from "./bridge";
import { defaults, eligible, type PetSettings } from "./pet/policy";
import "./pet/pet.css";
import EdgeCharacter from "./pet/EdgeCharacter";
import { idleLines } from "./pet/personality";
import { textOf } from "./domain";
type Message = {
  role: "user" | "assistant";
  text: string;
  profile?: string;
  question?: string;
};
const act = (action: string, value?: unknown) =>
  call<any>("pet_action", { action, value: value ?? null });
const service = (command: string, values: Record<string, unknown> = {}) =>
  call<any>("pet_service", { payload: { command, ...values } });
export default function Pet() {
  const bubble = new URLSearchParams(location.search).get("pet") === "bubble";
  const [settings, setSettings] = useState<PetSettings>(defaults),
    [material, setMaterial] = useState("solid"),
    [systemReduce, setSystemReduce] = useState(false);
  const [state, setState] = useState("idle"),
    [expanded, setExpanded] = useState(false),
    [visible, setVisible] = useState(true),
    [view, setView] = useState<"chat" | "settings" | "advanced" | "memory">(
      "chat",
    );
  const [asset, setAsset] = useState<any>(null);
  const [characters, setCharacters] = useState<{ id: string; label: string }[]>(
    [],
  );
  const [aside, setAside] = useState("");
  const [agentTask, setAgentTask] = useState<any>(null);
  const [coreConnected, setCoreConnected] = useState(false);
  const delegating = useRef(false);
  const [messages, setMessages] = useState<Message[]>([]),
    [text, setText] = useState(""),
    [busy, setBusy] = useState(false),
    [draft, setDraft] = useState(""),
    [error, setError] = useState(""),
    [snapshot, setSnapshot] = useState<any>(null),
    [memory, setMemory] = useState(true),
    [deletePending, setDeletePending] = useState(false),
    [reminder, setReminder] = useState(""),
    [due, setDue] = useState("");
  const taskId = useRef(""),
    taskStatus = useRef("");
  const current = useRef(""),
    composing = useRef(false),
    bottom = useRef<HTMLDivElement>(null),
    lastQuestion = useRef("");
  async function refresh() {
    const [s, m] = await Promise.all([
      service("ui_snapshot"),
      service("pet_memory"),
    ]);
    setSnapshot(s);
    setMemory(m.enabled);
  }
  function activity(value: string) {
    setState(value);
    void act("activity", { state: value }).catch(() => {});
  }
  useEffect(() => {
    document.documentElement.dataset.pet = "true";
    document.documentElement.dataset.petPart = bubble ? "bubble" : "character";
    let stopped = false;
    if (!bubble) void act("ready").catch((e) => setError(String(e)));
    const stops: (() => void)[] = [];
    const sub = async (name: string, fn: (v: any) => void) => {
      const stop = await listen(name, (e) => {
        if (!stopped) fn(e.payload);
      });
      if (stopped) stop();
      else stops.push(stop);
    };
    void act("state")
      .then((r) => {
        if (!stopped) {
          setSettings(r.settings);
          setExpanded(r.expanded);
          setMaterial(r.material?.material || "solid");
          setSystemReduce(r.material?.reduce_motion || false);
        }
      })
      .catch((e) => setError(String(e)));
    void sub("pet-dragged", () => {
      setState("dragging");
    });
    void sub("pet-drag-ended", () => setState("idle"));
    void sub("pet-settings", setSettings);
    void sub("pet-material", (v) => setMaterial(v.material || "solid"));
    void sub("pet-asset", setAsset);
    void call<any>("pet_asset", { action: "catalog" })
      .then((r) => setCharacters(r.items || []))
      .catch(() => {});
    void call<any>("pet_asset", { action: "load" })
      .then(setAsset)
      .catch((e) => setError(String(e)));
    void sub("pet-state", (v) => setExpanded(v.expanded));
    void sub("pet-visibility", setVisible);
    void sub("pet-activity", (v) => {
      setState(v.state);
      if (v.taskId) {
        taskId.current = v.taskId;
        taskStatus.current = "";
      }
    });
    if (bubble) {
      void call<any>("pet_core", { action: "status" })
        .then((r) => setCoreConnected(r.connected))
        .catch(() => {});
      void call<any>("pet_agent", { action: "status" })
        .then(acceptTask)
        .catch(() => {});
      void sub("pet-stream", (v) => {
        if (v.id === current.current && v.data.event === "draft")
          setDraft((t) => t + v.data.text);
      });
      void sub("task-stream", (v) => {
        if (v.taskId !== taskId.current) return;
        const t =
          v.kind === "snapshot"
            ? v.data
            : v.kind === "event" &&
                ["task.status", "task.created"].includes(v.data?.type)
              ? v.data.data
              : null;
        if (!t) return;
        setAgentTask(t);
        if (t.status === taskStatus.current) return;
        taskStatus.current = t.status;
        const terminal = [
          "completed",
          "incomplete",
          "failed",
          "cancelled",
          "timed_out",
        ].includes(t.status);
        activity(
          t.result?.task_outcome === "passed"
            ? "success"
            : terminal || t.status?.startsWith("requires_")
              ? "help"
              : "executing",
        );
        if (terminal || t.status?.startsWith("requires_"))
          setMessages((m) => [
            ...m,
            {
              role: "assistant",
              text: `任务状态：${({ completed: "完成", incomplete: "尚未完成", failed: "失败", cancelled: "已取消", timed_out: "超时", requires_approval: "等待你在任务窗口审批", requires_human: "需要你帮助" } as Record<string, string>)[t.status] || t.status}。\n任务验收：${t.result?.task_outcome || "unverified"}；验证：${t.verification_summary?.verification_status || t.result?.verification_status || "NOT_RUN"}。${textOf(t) ? "\n" + textOf(t).slice(0, 2400) : "请在任务窗口查看实际结果。"}`,
            },
          ]);
      });
      void sub("pet-notice", (v) => {
        setView("chat");
        setMessages((m) => [
          ...m,
          { role: "assistant", text: v.message || v.text || "有一条新提醒。" },
        ]);
        activity("waiting");
      });
      // Presentation can mount before the independent service has written its
      // runtime reference. Retry connection only; this never invokes a model.
      void (async () => {
        for (let attempt = 0; attempt < 20 && !stopped; attempt++) {
          try {
            await refresh();
            return;
          } catch {
            if (attempt === 19 && !stopped)
              setError("轻聊服务尚未连接，可在高级设置中启动服务。");
            else await new Promise((resolve) => setTimeout(resolve, 500));
          }
        }
      })();
    }
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.isComposing) void act("collapse");
    };
    window.addEventListener("keydown", key);
    const visibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stopped = true;
      stops.forEach((f) => f());
      window.removeEventListener("keydown", key);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages, draft, busy]);
  // One bounded, non-overlapping refresh per minute, only for opted-in reminders.
  // macOS Focus has no public status API here: focus protection defaults ON and
  // suppresses automatic bubbles until the user explicitly disables it.
  useEffect(() => {
    if (!bubble || !settings.proactive || settings.quiet) return;
    let cancelled = false,
      timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const s = await service("ui_snapshot");
        if (cancelled) return;
        setSnapshot(s);
        const seen: string[] = JSON.parse(
          localStorage.getItem("companion.pet.seen") || "[]",
        );
        const times: number[] = JSON.parse(
          localStorage.getItem("companion.pet.deliveries") || "[]",
        );
        const n = s.notices?.find(
          (n: any) =>
            !seen.includes(n.id) &&
            eligible(settings, n, s.runtime?.quiet_now, new Date(), times),
        );
        if (
          n &&
          s.proactive?.delivery === "enabled" &&
          s.proactive?.level !== "off"
        ) {
          await act("notice", n);
          localStorage.setItem(
            "companion.pet.seen",
            JSON.stringify([...seen, n.id].slice(-100)),
          );
          localStorage.setItem(
            "companion.pet.deliveries",
            JSON.stringify(
              [...times, Date.now()].filter((t) => Date.now() - t < 86400000),
            ),
          );
        }
      } catch {
      } finally {
        if (!cancelled) timer = setTimeout(poll, 60000);
      }
    };
    timer = setTimeout(poll, 60000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [bubble, settings]);
  function acceptTask(task: any) {
    if (!task?.id) return;
    taskId.current = task.id;
    setAgentTask(task);
    activity(
      ["running", "queued"].includes(task.status)
        ? "executing"
        : task.result?.task_outcome === "passed"
          ? "success"
          : "idle",
    );
    setMessages((m) => [
      ...m,
      {
        role: "assistant",
        text: `任务：${task.status}。验收：${task.result?.task_outcome || "unverified"}。\n${textOf(task)}`,
      },
    ]);
  }
  async function delegate(question: string, profile: string) {
    if (delegating.current) return;
    delegating.current = true;
    setError("");
    try {
      acceptTask(
        await call<any>("pet_agent", {
          action: "submit",
          text: question,
          agentProfile: profile,
        }),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      delegating.current = false;
    }
  }
  useEffect(() => {
    if (
      bubble ||
      expanded ||
      !visible ||
      settings.quiet ||
      !settings.banter ||
      state !== "idle"
    ) {
      setAside("");
      return;
    }
    let index = 0;
    let clear: ReturnType<typeof setTimeout>;
    const show = () => {
      setAside(idleLines[index++ % idleLines.length]);
      clear = setTimeout(() => setAside(""), 6000);
    };
    const first = setTimeout(show, 1800);
    const repeat = setInterval(show, 180000);
    return () => {
      clearTimeout(first);
      clearTimeout(clear);
      clearInterval(repeat);
    };
  }, [bubble, expanded, visible, settings.quiet, settings.banter, state]);
  useEffect(() => {
    if (!bubble) return;
    const measure = () => {
      const h = (selector: string) =>
        document.querySelector<HTMLElement>(selector)?.offsetHeight || 0;
      const conversation =
        document.querySelector<HTMLElement>(".pet-conversation");
      // Measure intrinsic message content, not the flex container's allocated
      // height, so returning from settings can shrink the bubble again.
      const contentHeight = conversation
        ? Array.from(conversation.children).reduce((sum, child) => {
            const style = getComputedStyle(child);
            return (
              sum +
              child.getBoundingClientRect().height +
              parseFloat(style.marginTop || "0") +
              parseFloat(style.marginBottom || "0")
            );
          }, 12)
        : 60;
      const height =
        view === "chat"
          ? h(".pet-header") +
            Math.min(260, contentHeight) +
            h(".pet-composer") +
            h(".pet-footnote") +
            h(".pet-task-controls") +
            8
          : 420;
      void act("resize_bubble", { height }).catch(() => {});
    };
    const timer = setTimeout(measure, 40);
    const observer = new ResizeObserver(measure);
    document
      .querySelectorAll(".pet-conversation article,.pet-welcome")
      .forEach((el) => observer.observe(el));
    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [bubble, messages, draft, error, view, agentTask, text]);
  async function send(question = text) {
    if (!question.trim() || busy) return;
    const q = question.trim();
    lastQuestion.current = q;
    setText("");
    setError("");
    setDraft("");
    setBusy(true);
    setView("chat");
    setMessages((m) => [...m, { role: "user", text: q }]);
    activity("thinking");
    const id = crypto.randomUUID();
    current.current = id;
    try {
      const r = await call<any>("pet_chat", { text: q, requestId: id });
      setDraft("");
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: r.text || r.reason || r.error || "暂时无法回答，请稍后重试。",
          profile: r.agent_profile,
          question: q,
        },
      ]);
      activity(
        r.status === "delegation_required"
          ? "waiting"
          : r.status === "ok"
            ? "reply"
            : "help",
      );
    } catch (e) {
      setError(String(e));
      activity("help");
    } finally {
      setBusy(false);
      setDraft("");
      current.current = "";
    }
  }
  async function update(next: PetSettings) {
    try {
      if (next.proactive !== settings.proactive)
        await service("proactive_settings", {
          level: next.proactive ? "low" : "off",
          delivery: next.proactive ? "enabled" : "silent",
        });
      setSettings(await act("settings", next));
    } catch (e) {
      setError(String(e));
    }
  }
  const handleError = (e: unknown) => setError(String(e));
  if (!bubble)
    return (
      <EdgeCharacter
        asset={asset}
        settings={settings}
        systemReduce={systemReduce}
        aside={aside}
      />
    );
  const toggle = (
    key: "topmost" | "animation" | "quiet" | "focus" | "proactive" | "banter",
    label: string,
  ) => (
    <label className="pet-setting">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={settings[key]}
        onChange={(e) => void update({ ...settings, [key]: e.target.checked })}
      />
    </label>
  );
  return (
    <section
      className="pet-chat-surface"
      data-material={material}
      data-reduce={systemReduce || !settings.animation}
    >
      <header className="pet-header">
        <div>
          <span className="pet-avatar">◉</span>
          <strong>
            {view === "chat"
              ? asset?.label || "DeepSeek 娘"
              : view === "memory"
                ? "我的记忆"
                : view === "advanced"
                  ? "高级设置"
                  : "宠物设置"}
          </strong>
          <small>
            {busy
              ? "想一想…"
              : view === "chat"
                ? "在你身边，轻轻陪伴"
                : "仅 Companion"}
          </small>
        </div>
        <nav>
          {view !== "chat" && (
            <button
              title="返回聊天"
              onClick={() => {
                setView("chat");
                setDeletePending(false);
              }}
            >
              <ChevronLeft size={17} />
            </button>
          )}
          <button
            title="宠物设置"
            onClick={() => {
              setView("settings");
              void refresh().catch(handleError);
            }}
          >
            <Settings size={16} />
          </button>
          <button title="收起" onClick={() => void act("collapse")}>
            <X size={16} />
          </button>
        </nav>
      </header>
      {view === "chat" ? (
        <>
          <div className="pet-conversation" aria-live="polite">
            {!messages.length && (
              <div className="pet-welcome">
                <span>哦鲸鲸…你来啦。</span>
                <p>本鲸在呢。今天想聊点什么？</p>
              </div>
            )}
            {messages.map((m, i) => (
              <article className={`pet-message ${m.role}`} key={i}>
                <Markdown
                  remarkPlugins={[remarkGfm]}
                  components={{ a: ({ children }) => <span>{children}</span> }}
                >
                  {m.text}
                </Markdown>
                {m.role === "assistant" && (
                  <button
                    className="pet-copy"
                    aria-label="复制回复"
                    onClick={() =>
                      navigator.clipboard.writeText(m.text).catch(handleError)
                    }
                  >
                    <Copy size={12} />
                  </button>
                )}
                {m.profile && (
                  <button
                    className="pet-handoff"
                    onClick={() =>
                      delegate(m.question || "", m.profile || "standard")
                    }
                  >
                    <ExternalLink size={13} />用
                    {m.profile === "minimal" ? "极简" : "标准"} Agent 处理 ·
                    仅本地
                  </button>
                )}
              </article>
            ))}
            {busy && (
              <article className="pet-message assistant">
                <p>{draft || "让我想一想…"}</p>
                {draft && <small>正在生成，完成后核对</small>}
              </article>
            )}
            {error && (
              <div className="pet-error" role="alert">
                {error}
                <button
                  disabled={busy || !lastQuestion.current}
                  onClick={() => void send(lastQuestion.current)}
                >
                  <RotateCcw size={12} />
                  重试
                </button>
              </div>
            )}
            <div ref={bottom} />
          </div>
          {agentTask?.id && (
            <div className="pet-task-controls">
              <button
                type="button"
                onClick={() =>
                  void call<any>("pet_agent", { action: "reconnect" })
                    .then(acceptTask)
                    .catch(handleError)
                }
              >
                刷新原任务
              </button>
              {![
                "completed",
                "incomplete",
                "failed",
                "cancelled",
                "timed_out",
              ].includes(agentTask.status) && (
                <button
                  type="button"
                  onClick={() =>
                    void call<any>("pet_agent", { action: "cancel" })
                      .then(acceptTask)
                      .catch(handleError)
                  }
                >
                  取消任务
                </button>
              )}
              {agentTask.status === "requires_approval" && (
                <button
                  type="button"
                  onClick={() =>
                    void call("pet_agent", { action: "review" }).catch(
                      handleError,
                    )
                  }
                >
                  在主窗口核对审批
                </button>
              )}
            </div>
          )}
          <form
            className="pet-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              aria-label="回复 DeepSeek 娘"
              placeholder="和 DeepSeek 娘说句话…"
              rows={1}
              maxLength={4000}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(100, e.target.scrollHeight)}px`;
              }}
              onCompositionStart={() => {
                composing.current = true;
              }}
              onCompositionEnd={() => {
                composing.current = false;
              }}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing &&
                  !composing.current &&
                  e.keyCode !== 229
                ) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button aria-label="发送消息" disabled={busy || !text.trim()}>
              <ArrowUp size={18} />
            </button>
          </form>
          <footer className="pet-footnote">
            本地轻聊 · 操作由 Core 授权执行
          </footer>
        </>
      ) : (
        <div className="pet-settings-body">
          {view === "settings" && (
            <>
              <button
                className="pet-row-button"
                onClick={() =>
                  void call<any>("pet_asset", { action: "import" })
                    .then(setAsset)
                    .catch(handleError)
                }
              >
                导入个人角色素材
              </button>
              <h4>本机任务</h4>
              <button
                className="pet-row-button"
                onClick={() => {
                  void call("pet_core", { action: "setup" }).catch(handleError);
                }}
              >
                打开主窗口完成设置或查看任务
              </button>
              <button
                className="pet-row-button"
                onClick={() => {
                  void call<any>("pet_core", { action: "connect" })
                    .then((r) => {
                      if (!r.cancelled) {
                        setCoreConnected(r.connected);
                        setError("");
                      }
                    })
                    .catch(handleError);
                }}
              >
                {coreConnected ? "重新连接 Core" : "连接本机 Core"}
              </button>
              <p className="pet-explanation">
                {coreConnected
                  ? "已连接。任务与审批沿用主窗口，关闭气泡不会取消任务。"
                  : "选择已有的 Core 数据目录后，可将工具任务交给 Agent。"}
              </p>
              <h4>边缘位置</h4>
              <div className="pet-character-list">
                {[
                  "TOP_LEFT",
                  "TOP_RIGHT",
                  "LEFT_EDGE",
                  "RIGHT_EDGE",
                  "BOTTOM_LEFT",
                  "BOTTOM_RIGHT",
                ].map((anchor, i) => (
                  <button
                    key={anchor}
                    onClick={() => {
                      void act("collapse")
                        .then(() =>
                          call("pet_edge", { action: "anchor", value: anchor }),
                        )
                        .catch(handleError);
                    }}
                  >
                    {
                      [
                        "左上探头",
                        "右上探头",
                        "左边探头",
                        "右边探头",
                        "左下探头",
                        "右下探头",
                      ][i]
                    }
                  </button>
                ))}
              </div>
              <button
                className="pet-row-button"
                onClick={() => {
                  void call<any>("pet_asset", { action: "import_edge" })
                    .then(() => call<any>("pet_asset", { action: "load" }))
                    .then(setAsset)
                    .catch(handleError);
                }}
              >
                导入当前角色探头姿态包
              </button>
              <h4>换个形象</h4>
              <div className="pet-character-list">
                {characters.map((c) => (
                  <button
                    key={c.id}
                    aria-pressed={asset?.id === c.id}
                    onClick={() =>
                      void call<any>("pet_asset", {
                        action: "select_local",
                        id: c.id,
                      })
                        .then(setAsset)
                        .catch(handleError)
                    }
                  >
                    {c.label}
                  </button>
                ))}
              </div>
              {!characters.length && (
                <p className="pet-explanation">
                  可以导入你本机已有的透明角色图集。
                </p>
              )}
              {toggle("banter", "偶尔碎碎念 · 哦鲸鲸")}
              {toggle("topmost", "总在上方")}
              {toggle("animation", "轻柔动画")}
              <label className="pet-setting">
                <span>角色大小</span>
                <input
                  aria-label="角色大小"
                  type="range"
                  min=".7"
                  max="1.8"
                  step=".1"
                  value={settings.size}
                  onChange={(e) =>
                    void update({ ...settings, size: +e.target.value })
                  }
                />
              </label>
              {toggle("quiet", "安静模式")}
              {toggle("focus", "保护专注 · 暂停自动气泡")}
              {toggle("proactive", "允许主动提醒")}
              <p className="pet-explanation">
                默认不观察屏幕、不监听键盘。保护专注开启时，提醒保留在消息中，不自动弹出。
              </p>
              <label className="pet-setting">
                <span>保存聊天记忆</span>
                <input
                  type="checkbox"
                  checked={memory}
                  onChange={(e) => {
                    void service("pet_memory", { enabled: e.target.checked })
                      .then((r) => setMemory(r.enabled))
                      .catch(handleError);
                  }}
                />
              </label>
              <button
                className="pet-row-button"
                onClick={() => {
                  setView("memory");
                  void refresh().catch(handleError);
                }}
              >
                查看、导出或清理记忆 <span>›</span>
              </button>
              <h4>给未来的自己留句话</h4>
              <input
                aria-label="提醒内容"
                placeholder="提醒内容"
                value={reminder}
                maxLength={300}
                onChange={(e) => setReminder(e.target.value)}
              />
              <input
                aria-label="提醒时间"
                type="datetime-local"
                value={due}
                onChange={(e) => setDue(e.target.value)}
              />
              <button
                disabled={!reminder.trim() || !due}
                onClick={() =>
                  service("set_reminder", {
                    text: reminder,
                    due_at: new Date(due).getTime() / 1000,
                    confirmed: true,
                  })
                    .then(() => {
                      setReminder("");
                      setDue("");
                      return refresh();
                    })
                    .catch(handleError)
                }
              >
                保存提醒
              </button>
              {snapshot?.reminders
                ?.filter((r: any) => !r.delivered)
                .map((r: any) => (
                  <p key={r.id}>
                    {r.text}
                    <button
                      onClick={() =>
                        service("delete_reminder", { id: r.id })
                          .then(refresh)
                          .catch(handleError)
                      }
                    >
                      取消
                    </button>
                  </p>
                ))}
              <button
                className="pet-row-button"
                onClick={() => setView("advanced")}
              >
                高级设置 <span>›</span>
              </button>
              <div className="pet-button-pair">
                <button onClick={() => void act("hide")}>隐藏角色</button>
                <button onClick={() => void act("quit")}>退出宠物</button>
              </div>
            </>
          )}
          {view === "advanced" && (
            <>
              <p className="pet-explanation">
                独立轻量模型：
                {snapshot?.runtime?.model?.backend || "按 Companion 配置"}
                。问候优先使用规则，聊天不会自动改走主 Agent 的云端模型。
              </p>
              <label>
                最短提示间隔（分钟）
                <input
                  type="number"
                  min="1"
                  max="1440"
                  value={settings.cooldown_minutes}
                  onChange={(e) =>
                    void update({
                      ...settings,
                      cooldown_minutes: +e.target.value,
                    })
                  }
                />
              </label>
              <label>
                每天最多提示
                <input
                  type="number"
                  min="0"
                  max="20"
                  value={settings.daily_limit}
                  onChange={(e) =>
                    void update({ ...settings, daily_limit: +e.target.value })
                  }
                />
              </label>
              <label>
                夜间安静时间
                <div className="pet-button-pair">
                  <input
                    aria-label="安静开始小时"
                    type="number"
                    min="0"
                    max="23"
                    value={settings.quiet_start}
                    onChange={(e) =>
                      void update({ ...settings, quiet_start: +e.target.value })
                    }
                  />
                  <span>至</span>
                  <input
                    aria-label="安静结束小时"
                    type="number"
                    min="0"
                    max="23"
                    value={settings.quiet_end}
                    onChange={(e) =>
                      void update({ ...settings, quiet_end: +e.target.value })
                    }
                  />
                </div>
              </label>
              <h4>允许的提醒</h4>
              {[
                ["explicit_reminder", "我设置的提醒"],
                ["localpilot_completed", "任务完成"],
                ["repeated_error", "服务需要帮助"],
                ["deadline", "已授权待办"],
              ].map(([key, label]) => (
                <label className="pet-setting" key={key}>
                  {label}
                  <input
                    type="checkbox"
                    checked={settings.event_allowlist.includes(key)}
                    onChange={(e) =>
                      void update({
                        ...settings,
                        event_allowlist: e.target.checked
                          ? [...settings.event_allowlist, key]
                          : settings.event_allowlist.filter((k) => k !== key),
                      })
                    }
                  />
                </label>
              ))}
              <h4>轻聊服务与本地模型</h4>
              <div className="pet-button-pair">
                <button
                  onClick={() =>
                    call("pet_runtime", { action: "start" })
                      .then(refresh)
                      .catch(handleError)
                  }
                >
                  启动轻聊服务
                </button>
                <button
                  onClick={() =>
                    call("pet_runtime", { action: "stop" })
                      .then(() =>
                        setError("轻聊服务已停止；Core 任务继续运行。"),
                      )
                      .catch(handleError)
                  }
                >
                  停止轻聊服务
                </button>
              </div>
              <button
                onClick={() =>
                  call<any>("pet_runtime", { action: "choose_model" })
                    .then((r) => {
                      if (r.text) setError(r.text);
                    })
                    .catch(handleError)
                }
              >
                选择已有的 0.8B 模型
              </button>
              <button
                onClick={() =>
                  call<any>("pet_runtime", { action: "choose_python" })
                    .then((r) => {
                      if (r.text) setError(r.text);
                    })
                    .catch(handleError)
                }
              >
                选择已有的模型运行程序
              </button>
              <button
                onClick={() =>
                  service("pause_observation", { paused: true })
                    .then(refresh)
                    .catch(handleError)
                }
              >
                暂停所有观察
              </button>
              <p className="pet-explanation">
                原生材质：{material}。模型上下文、空闲卸载和连接由独立 Companion
                服务配置管理；此版本不修改主 Agent 设置。
              </p>
            </>
          )}
          {view === "memory" && (
            <>
              <p className="pet-explanation">
                关闭记忆后，新聊天不保存，也不读取既有记忆。清理会删除 Companion
                数据并暂停观察；不会取消 Core 任务。
              </p>
              <div className="pet-button-pair">
                <button
                  onClick={() =>
                    service("pet_export")
                      .then((r) => {
                        setError(`已导出：${r.path}`);
                      })
                      .catch(handleError)
                  }
                >
                  导出数据
                </button>
                <button
                  onClick={() => {
                    if (!deletePending) {
                      setDeletePending(true);
                      return;
                    }
                    void service("clear", {
                      confirmation: "DELETE_COMPANION_MEMORY",
                    })
                      .then(() => {
                        setMessages([]);
                        setDeletePending(false);
                        return refresh();
                      })
                      .catch(handleError);
                  }}
                >
                  {deletePending ? "确认永久清理" : "清理全部记忆"}
                </button>
              </div>
              {snapshot?.memories?.map((m: any) => (
                <article className="pet-memory" key={m.id}>
                  {m.summary || m.text}
                </article>
              ))}
            </>
          )}
          {error && (
            <p role="alert" className="pet-error">
              {error}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

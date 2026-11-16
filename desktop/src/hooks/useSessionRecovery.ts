import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { listen } from "@tauri-apps/api/event";
import { call, desktop } from "../bridge";
import { textOf, type Json, type Message, type Task } from "../domain";
import { taskPreferences, type Preferences } from "../preferences";
import type { TaskState } from "./useTaskState";

export interface ChatDraft {
  preferences: Preferences;
  model: string;
  title: string;
  input?: string;
  scope: string;
}

export function restoredConversation(
  task: Task,
  tasks: Task[],
  turns: Record<string, Json>,
  drafts: Record<string, ChatDraft>,
  scope: string,
  defaults: Preferences,
  model: string,
) {
  const cached = drafts[task.session_id];
  const same = [
    ...tasks.filter(
      (value) => value.session_id === task.session_id && value.id !== task.id,
    ),
    task,
  ].sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
  const messages: Message[] = same.flatMap((value) => [
    ...(turns[value.id]?.input || value.user_input
      ? [
          {
            id: `user-${value.id}`,
            role: "user" as const,
            text: turns[value.id]?.input || value.user_input,
          },
        ]
      : []),
    {
      id: `answer-${value.id}`,
      role: "assistant" as const,
      text: textOf(value) || "该任务暂无最终文本。可在右侧查看当前状态和事件。",
      taskId: value.id,
      source:
        turns[value.id] || value.user_input
          ? "服务快照 · 原请求保存在本机"
          : "服务快照 · 此客户端未保存原始提问",
    },
  ]);
  return {
    input: cached?.scope === scope ? cached.input || "" : "",
    preferences:
      cached?.scope === scope
        ? cached.preferences
        : turns[task.id]?.preferences || taskPreferences(task, defaults),
    model: task.session_model || task.model || model,
    messages,
  };
}
export type RestoredConversation = ReturnType<typeof restoredConversation>;

export function isMissingSession(error: unknown): boolean {
  const match = /^(?:Error: )?HTTP 404 · (.+)$/s.exec(String(error));
  if (!match) return false;
  try {
    return JSON.parse(match[1])?.error?.code === "session_not_found";
  } catch {
    return false;
  }
}

interface RecoveryOptions {
  preferencesReady: boolean;
  completed: boolean;
  health: Json | null;
  historyReady: boolean;
  restoreDone: RefObject<boolean>;
  drafts: Record<string, ChatDraft>;
  chatId: string;
  scope: string;
  defaults: Preferences;
  model: string;
  onOpen: (task: Task, view: RestoredConversation) => void;
  onDraft: (draft: ChatDraft) => void;
  onFreshDraft: (draft?: ChatDraft, missingSession?: boolean) => void;
  onPreferences: (preferences: Preferences) => void;
  onError: (error: unknown) => void;
}

export function useSessionRecovery(state: TaskState, options: RecoveryOptions) {
  const current = useRef({ state, options });
  current.current = { state, options };
  const [confirmed, setConfirmed] = useState<{
    id: string;
    scope: string;
  } | null>(null);
  const serviceScope = `${options.scope}|${options.health?.client_generation || ""}`;
  const confirmSession = useCallback((id: string) => {
    const { options } = current.current;
    setConfirmed({
      id,
      scope: `${options.scope}|${options.health?.client_generation || ""}`,
    });
  }, []);
  const openTask = useCallback((task: Task) => {
    const { state, options } = current.current;
    const view = restoredConversation(
      task,
      state.tasks,
      state.turns,
      options.drafts,
      options.scope,
      options.defaults,
      options.model,
    );
    localStorage.setItem("lp.currentTask", JSON.stringify(task.id));
    options.onOpen(task, view);
    if (desktop)
      void call<Preferences | null>("session_preferences", {
        sessionId: task.session_id,
        value: null,
      })
        .then((preferences) => {
          if (preferences && state.selectedRef.current === task.id)
            current.current.options.onPreferences(preferences);
        })
        .catch(options.onError);
  }, []);
  useEffect(() => {
    if (
      !options.preferencesReady ||
      !options.completed ||
      !options.health ||
      !options.historyReady ||
      options.restoreDone.current
    )
      return;
    let id = "";
    try {
      id = JSON.parse(localStorage.getItem("lp.currentTask") || '""');
    } catch {
      /* Broken local selection has no authority over server history. */
    }
    const task =
      state.tasks.find((value) => value.id === id) ||
      state.tasks
        .filter((value) => value.session_id === options.chatId)
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))[0];
    const cached = options.drafts[options.chatId];
    const draft = cached?.scope === options.scope ? cached : undefined;
    if (task) {
      openTask(task);
      options.restoreDone.current = true;
      return;
    }
    if (!options.chatId.startsWith("sess_")) {
      if (draft) options.onDraft(draft);
      else if (cached) options.onFreshDraft();
      options.restoreDone.current = true;
      return;
    }
    // A cached id is a selection, not evidence that the connected service
    // owns this Session. Only its authenticated 404 permits a fresh draft.
    let disposed = false;
    void (async () => {
      try {
        const session = await call<Json>("api", {
          method: "GET",
          path: `/localpilot/v1/sessions/${options.chatId}`,
        });
        if (disposed) return;
        const taskId = session.active_task_id || session.last_task_id;
        if (taskId) {
          const recovered = await call<Task>("api", {
            method: "GET",
            path: `/localpilot/v1/tasks/${taskId}`,
          });
          if (disposed) return;
          state.updateTask(recovered);
          openTask(recovered);
        } else {
          confirmSession(session.id);
          if (draft) options.onDraft(draft);
        }
        options.restoreDone.current = true;
      } catch (error) {
        if (disposed) return;
        if (isMissingSession(error)) {
          options.onFreshDraft(draft, true);
          options.restoreDone.current = true;
        } else options.onError(error);
      }
    })();
    return () => {
      disposed = true;
    };
  }, [
    options.preferencesReady,
    options.completed,
    options.health,
    options.scope,
    options.chatId,
    state.tasks,
    options.historyReady,
    openTask,
    confirmSession,
  ]);
  useEffect(() => {
    if (!desktop) return;
    let disposed = false;
    const load = (id: string) => {
      if (!/^resp_[a-zA-Z0-9]+$/.test(id)) return;
      void call<Task>("api", {
        method: "GET",
        path: `/localpilot/v1/tasks/${id}`,
      })
        .then((task) => {
          if (!disposed) {
            current.current.state.updateTask(task);
            openTask(task);
          }
        })
        .catch((error) => current.current.options.onError(error));
    };
    const id = new URLSearchParams(location.search).get("petTask");
    if (id) load(id);
    const stop = listen<Json>("pet-review-task", (event) =>
      load(event.payload.task_id),
    );
    return () => {
      disposed = true;
      void stop.then((off) => off());
    };
  }, [openTask]);
  const selected = state.tasks.find((task) => task.id === state.selected);
  const sessionId =
    options.historyReady && options.health
      ? selected?.session_id ||
        (confirmed?.scope === serviceScope && confirmed.id === options.chatId
          ? confirmed.id
          : null)
      : null;
  return { openTask, sessionId, confirmSession };
}

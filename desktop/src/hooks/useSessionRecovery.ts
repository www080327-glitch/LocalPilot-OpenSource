import { useCallback, useEffect, useRef, type RefObject } from "react";
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
  onPreferences: (preferences: Preferences) => void;
  onError: (error: unknown) => void;
}

export function useSessionRecovery(state: TaskState, options: RecoveryOptions) {
  const current = useRef({ state, options });
  current.current = { state, options };
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
    options.restoreDone.current = true;
    let id = "";
    try {
      id = JSON.parse(localStorage.getItem("lp.currentTask") || '""');
    } catch {
      /* Broken local selection has no authority over server history. */
    }
    const task = state.tasks.find((value) => value.id === id);
    if (task) openTask(task);
    else if (options.drafts[options.chatId]?.scope === options.scope)
      options.onDraft(options.drafts[options.chatId]);
  }, [
    options.preferencesReady,
    options.completed,
    options.health,
    state.tasks,
    options.historyReady,
    openTask,
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
  return openTask;
}

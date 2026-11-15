import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { call, desktop, streamListener } from "../bridge";
import {
  latestTask,
  reconciledStreamText,
  terminal,
  textOf,
  type Json,
  type Message,
  type StreamEvent,
  type Task,
} from "../domain";

export function useTaskState(onActionRequired: () => void) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [turns, setTurns] = useState<Record<string, Json>>({});
  const [events, setEvents] = useState<Record<string, StreamEvent[]>>({});
  const [delta, setDelta] = useState<Record<string, string>>({});
  const [stream, setStream] = useState("idle");
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const taskSnapshots = useRef<Record<string, Task>>({});
  const streamedSequence = useRef<Record<string, number>>({});
  const connectionError = useRef("");
  const updateTask = useCallback(
    (incoming: Task) => {
      if (latestTask(taskSnapshots.current[incoming.id], incoming) !== incoming)
        return;
      taskSnapshots.current[incoming.id] = incoming;
      if (incoming.required_action && incoming.id === selectedRef.current)
        onActionRequired();
      const task = incoming.service?.route_decision?.selected
        ? { ...incoming, model: incoming.service.route_decision.selected }
        : incoming;
      setTasks((old) =>
        [task, ...old.filter((value) => value.id !== task.id)].sort(
          (a, b) => (b.created_at || 0) - (a.created_at || 0),
        ),
      );
      setMessages((old) =>
        old.map((message) =>
          message.taskId === task.id && message.role === "assistant"
            ? { ...message, text: textOf(task) || message.text }
            : message,
        ),
      );
    },
    [onActionRequired],
  );
  const mergeTasks = useCallback((incoming: Task[]) => {
    setTasks(
      incoming
        .map((task) => {
          const latest = latestTask(taskSnapshots.current[task.id], task);
          taskSnapshots.current[task.id] = latest;
          return latest;
        })
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0)),
    );
  }, []);
  const reset = useCallback(() => {
    setTurns({});
    setTasks([]);
    setSelected(null);
    setMessages([]);
    setEvents({});
    setDelta({});
    taskSnapshots.current = {};
    streamedSequence.current = {};
  }, []);
  return {
    tasks,
    setTasks,
    selected,
    setSelected,
    messages,
    setMessages,
    turns,
    setTurns,
    events,
    setEvents,
    delta,
    setDelta,
    stream,
    setStream,
    selectedRef,
    taskSnapshots,
    streamedSequence,
    connectionError,
    updateTask,
    mergeTasks,
    reset,
  };
}
export type TaskState = ReturnType<typeof useTaskState>;

export function useTaskStream(
  state: TaskState,
  options: {
    preview: boolean;
    connected: boolean;
    showError: (error: unknown) => void;
    setError: Dispatch<SetStateAction<string>>;
  },
) {
  const {
    selected,
    tasks,
    selectedRef,
    streamedSequence,
    connectionError,
    updateTask,
    setEvents,
    setDelta,
    setStream,
  } = state;
  const { preview, connected, showError, setError } = options;
  const active = tasks.find((task) => task.id === selected);
  useEffect(() => {
    let off: (() => void) | undefined;
    let disposed = false;
    streamListener((payload) => {
      if (disposed) return;
      const id = payload.taskId;
      if (payload.kind === "event") {
        const e = payload.data as StreamEvent;
        // Text deltas already accumulate in delta; they are not timeline
        // facts and keeping a second copy re-renders the entire event list.
        if (!(e.type === "runtime.event" && e.data.type === "TextDelta")) {
          setEvents((old) => ({
            ...old,
            [id]: [
              ...(old[id] || []).filter((v) => v.sequence !== e.sequence),
              e,
            ].slice(-500),
          }));
        }
        if (e.type === "task.status" || e.type === "task.created")
          updateTask(e.data as Task);
        if (
          e.type === "runtime.event" &&
          e.sequence > (streamedSequence.current[id] || 0)
        ) {
          streamedSequence.current[id] = e.sequence;
          if (e.data.type === "ModelResponseStarted")
            setDelta((old) => ({ ...old, [id]: "" }));
          if (e.data.type === "TextDelta")
            setDelta((old) => ({
              ...old,
              [id]: (old[id] || "") + (e.data.data?.text || ""),
            }));
        }
      }
      if (payload.kind === "snapshot") {
        const snapshot = payload.data as Task;
        updateTask(snapshot);
        const recoveredText = reconciledStreamText(
          snapshot,
          streamedSequence.current[id] || 0,
          payload.reconciled === true,
        );
        if (recoveredText !== null) {
          // The snapshot replaces a missing SSE prefix only when it is at
          // least as recent as the events already observed in this GUI.
          streamedSequence.current[id] = snapshot.last_event_id;
          setDelta((old) => ({ ...old, [id]: recoveredText }));
        }
      }
      if (
        id === selectedRef.current &&
        [
          "connected",
          "connecting",
          "reconnecting",
          "disconnected",
          "snapshot",
        ].includes(payload.kind)
      )
        setStream(payload.kind);
      if (payload.kind === "disconnected" && id === selectedRef.current) {
        connectionError.current = payload.error;
        setError(payload.error);
      }
      if (
        ["connected", "snapshot"].includes(payload.kind) &&
        id === selectedRef.current
      ) {
        setError((old) => (old === connectionError.current ? "" : old));
        connectionError.current = "";
      }
    }).then((un) => {
      if (disposed) un();
      else off = un;
    });
    return () => {
      disposed = true;
      off?.();
    };
  }, [updateTask]);
  useEffect(() => {
    if (preview || !selected || !desktop) return;
    setStream("connecting");
    call("watch_task", { taskId: selected, after: 0 }).catch(showError);
    return () => {
      call("unwatch_task", { taskId: selected }).catch(() => {});
    };
  }, [selected, preview, showError]);
  useEffect(() => {
    if (!selected || preview || !connected) return;
    const active = tasks.find((t) => t.id === selected);
    if (!active || (terminal.has(active.status) && active.quiescent)) return;
    const timer = window.setInterval(
      () =>
        call<Task>("api", {
          method: "GET",
          path: `/localpilot/v1/tasks/${selected}`,
        })
          .then(updateTask)
          .catch(() => setStream("disconnected")),
      active.quiescent ? 12000 : 4500,
    );
    return () => window.clearInterval(timer);
  }, [
    selected,
    active?.status,
    active?.quiescent,
    preview,
    connected,
    updateTask,
  ]);
}

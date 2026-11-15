import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { call, desktop } from "../bridge";
import {
  compatible,
  errorAfterHealthyConnection,
  type Json,
  type Model,
  type NativeProfile,
} from "../domain";
import { routingSupported } from "../preferences";
import type { TaskState } from "./useTaskState";
const emptyProfile: NativeProfile = {
  home: "",
  cli: "",
  origin: "",
  workspace: "",
};

export function useServiceConnection(
  taskState: TaskState,
  options: {
    setModel: Dispatch<SetStateAction<string>>;
    setError: Dispatch<SetStateAction<string>>;
    setFormHome: Dispatch<SetStateAction<string>>;
    setFormCli: Dispatch<SetStateAction<string>>;
    restoreDone: RefObject<boolean>;
    showError: (error: unknown) => void;
  },
) {
  const { reset, mergeTasks, setTurns, connectionError } = taskState;
  const {
    setModel,
    setError,
    setFormHome,
    setFormCli,
    restoreDone,
    showError,
  } = options;
  const [profile, setProfile] = useState(emptyProfile);
  const [health, setHealth] = useState<Json | null>(null);
  const [compHealth, setCompHealth] = useState<Json | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [pending, setPending] = useState<Json[]>([]);
  const [routingCaps, setRoutingCaps] = useState<Json | null>(null);
  const [historyReady, setHistoryReady] = useState(false);
  const activeIdentity = useRef("");
  const refreshSequence = useRef(0);
  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    setHistoryReady(false);
    try {
      const h = await call<Json>("api", { method: "GET", path: "/healthz" });
      const activeProfile = await call<NativeProfile>("profile");
      if (sequence !== refreshSequence.current) return;
      const identity = `${activeProfile.origin}|${h.client_subject}|${h.client_generation || ""}`;
      if (activeIdentity.current && activeIdentity.current !== identity) {
        setPending([]);
        reset();
        setModel("");
        restoreDone.current = false;
      }
      activeIdentity.current = identity;
      setPending([]);
      setHealth(h);
      if (!compatible(h))
        throw new Error("服务契约不兼容；请在连接设置中检查版本。");
      const [m, t] = await Promise.all([
        call<Json>("api", {
          method: "GET",
          path: "/localpilot/v1/model-registry",
        }),
        call<Json>("api", { method: "GET", path: "/localpilot/v1/tasks" }),
      ]);
      if (sequence !== refreshSequence.current) return;
      setModels(m.models || []);
      let automaticSupported = false;
      try {
        const cap = await call<Json>("routing_capabilities");
        setRoutingCaps(cap);
        automaticSupported = routingSupported(h, cap);
      } catch {
        setRoutingCaps(null);
      }
      mergeTasks(t.tasks || []);
      setModel(
        (old) =>
          ((old === "__auto__" && automaticSupported) ||
          m.models?.some(
            (v: Model) =>
              v.id === old &&
              v.deployment_status === "ready" &&
              !v.reasoning_only &&
              v.capabilities?.includes("tool_calling"),
          )
            ? old
            : "") ||
          (automaticSupported ? "__auto__" : "") ||
          m.models?.find(
            (v: Model) =>
              v.deployment_status === "ready" &&
              !v.reasoning_only &&
              v.capabilities?.includes("tool_calling"),
          )?.id ||
          "",
      );
      try {
        setCompHealth(await call("companion", { command: "status" }));
      } catch {
        setCompHealth(null);
      }
      setPending(await call<Json[]>("pending_submissions"));
      setTurns(await call<Record<string, Json>>("submission_history"));
      setHistoryReady(true);
      setError((old) =>
        errorAfterHealthyConnection(old, connectionError.current),
      );
      connectionError.current = "";
    } catch (e) {
      if (sequence !== refreshSequence.current) return;
      setHealth(null);
      setModels([]);
      connectionError.current = String(e);
      throw e;
    }
  }, []);
  useEffect(() => {
    if (!desktop) return;
    const sync = () => {
      void refresh().catch(() => {});
    };
    window.addEventListener("focus", sync);
    const timer = window.setInterval(sync, 30000);
    return () => {
      window.removeEventListener("focus", sync);
      window.clearInterval(timer);
    };
  }, [refresh]);
  useEffect(() => {
    if (desktop)
      call<NativeProfile>("profile")
        .then((p) => {
          setProfile(p);
          setFormHome(p.home);
          setFormCli(p.cli);
          if (p.home)
            refresh().catch(async () => {
              if (p.maintenance_return) {
                showError(
                  "统一维护已返回。请先检查升级回执，再在安装、服务与数据恢复中显式恢复服务。",
                );
                return;
              }
              // One bounded recovery per application launch; never replay Agent tasks.
              try {
                await call("product_control", {
                  operation: "service_control",
                  args: { module: "core", action: "recover", confirmed: true },
                });
                await refresh();
              } catch {
                showError(
                  "Core 未连接。请在设置的“安装、服务与数据恢复”中恢复服务；历史与原请求保留。",
                );
              }
            });
        })
        .catch(showError);
  }, [refresh, showError]);
  return {
    profile,
    setProfile,
    health,
    setHealth,
    compHealth,
    setCompHealth,
    models,
    setModels,
    pending,
    setPending,
    routingCaps,
    setRoutingCaps,
    historyReady,
    setHistoryReady,
    refresh,
  };
}

import { useRef } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Cloud,
  Monitor,
} from "lucide-react";
import { label, type Model } from "../domain";
import { Popover } from "./Popover";

type ModelPickerProps = {
  model: string;
  chosen?: Model;
  models: Model[];
  loadingModel: string;
  busy: boolean;
  routeCloud: boolean;
  supportedRouting: boolean;
  open: boolean;
  onOpen: (open: boolean) => void;
  onSelect: (id: string) => void;
  onAutoRoute: () => void;
  onLibrary: () => void;
};

export function ModelPicker({
  model,
  chosen,
  models,
  loadingModel,
  busy,
  routeCloud,
  supportedRouting,
  open,
  onOpen,
  onSelect,
  onAutoRoute,
  onLibrary,
}: ModelPickerProps) {
  const modelMenu = useRef<HTMLDivElement>(null);
  return (
    <div className="model-anchor" ref={modelMenu}>
      <button
        className="model-trigger"
        aria-label="选择模型"
        disabled={!!loadingModel || busy}
        onClick={() => onOpen(!open)}
      >
        <span
          className={`model-indicator ${loadingModel || chosen?.deployment_status !== "ready" ? "unavailable" : routeCloud ? "cloud" : ""}`}
        />
        <span>
          {loadingModel
            ? `正在加载 ${loadingModel}…`
            : chosen?.model || "选择模型"}
        </span>
        <ChevronDown size={11} />
      </button>
      {open && (
        <Popover
          className="model-menu"
          anchor={modelMenu}
          onClose={() => onOpen(false)}
        >
          <div className="menu-label">
            选择模型
            <span>已配置且声明支持工具 · 在线状态未验证</span>
          </div>
          {supportedRouting && (
            <button onClick={onAutoRoute}>Core 自动选择 · 新会话选路</button>
          )}
          {models.length ? (
            models.map((m) => (
              <button
                key={m.id}
                disabled={!!m.reasoning_only || !!loadingModel || busy}
                title={
                  m.reasoning_only
                    ? "此路由用于 Companion 轻量对话，不具备标准 Agent 工具能力"
                    : undefined
                }
                onClick={() => {
                  void onSelect(m.id);
                }}
                className={model === m.id ? "selected" : ""}
              >
                <span>
                  {[
                    "deepseek",
                    "deepseek-native",
                    "remote-openai",
                    "remote-vllm",
                  ].includes(m.adapter) ? (
                    <Cloud size={16} />
                  ) : (
                    <Monitor size={16} />
                  )}
                </span>
                <div>
                  <strong>{m.model}</strong>
                  <small>
                    {m.id} · {label(m.deployment_status)} ·{" "}
                    {m.context_budget
                      ? `${Math.round(m.context_budget / 1024)}k`
                      : "上下文未知"}
                  </small>
                </div>
                {model === m.id ? (
                  <Check size={14} />
                ) : m.deployment_status !== "ready" ? (
                  <AlertTriangle size={13} />
                ) : null}
              </button>
            ))
          ) : (
            <div className="menu-empty">
              无可用标准 Agent；请先在模型库加载或配置模型。
            </div>
          )}
          <button
            onClick={() => {
              onOpen(false);
              onLibrary();
            }}
          >
            模型详情、加载与设置 →
          </button>
          <p>不可用及未加载模型仍可在模型库检查或加载。</p>
        </Popover>
      )}
    </div>
  );
}

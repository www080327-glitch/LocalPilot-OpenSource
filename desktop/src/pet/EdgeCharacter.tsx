import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { call } from "../bridge";
import type { PetSettings } from "./policy";
const W = 240,
  H = 220;
export default function EdgeCharacter({
  asset,
  settings,
  systemReduce,
  aside,
}: {
  asset: any;
  settings: PetSettings;
  systemReduce: boolean;
  aside: string;
}) {
  const [edge, setEdge] = useState<any>(null),
    [pack, setPack] = useState<any>(null),
    [error, setError] = useState("");
  useEffect(() => setPack(asset?.edge), [asset]);
  useEffect(() => {
    let stopped = false;
    const stops: (() => void)[] = [];
    const sub = async (name: string, fn: (v: any) => void) => {
      const stop = await listen(name, (e) => {
        if (!stopped) fn(e.payload);
      });
      if (stopped) stop();
      else stops.push(stop);
    };
    void sub("pet-edge", setEdge);
    void sub("pet-edge-asset", setPack);
    void call("pet_edge", { action: "state" })
      .then(setEdge)
      .catch((e) => setError(String(e)));
    return () => {
      stopped = true;
      stops.forEach((s) => s());
    };
  }, []);
  const act = (action: string) =>
    void call("pet_edge", { action }).catch((e) => setError(String(e)));
  const sourceFor = (name: string) =>
    name === "legacy" ? asset : name === "edge" ? pack : pack?.extras?.[name];
  const art = (part: any, cls: string) => {
    if (!part) return null;
    const src = sourceFor(part.source);
    if (!src?.url) return null;
    const r = part.rect || [0, 0, 1, 1],
      b = part.box || [0, 0, 0, 0],
      scale = b[2] / r[2];
    return (
      <span
        className={`edge-sprite ${cls}`}
        role="img"
        aria-label={asset?.label || "角色"}
        style={{
          left: b[0],
          top: b[1],
          width: b[2],
          height: b[3],
          opacity: part.opacity ?? 1,
          backgroundImage: `url(${src.url})`,
          backgroundSize: `${src.width * scale}px ${src.height * scale}px`,
          backgroundPosition: `${-r[0] * scale}px ${-r[1] * scale}px`,
          transform: `rotate(${part.angle || 0}deg)`,
          transformOrigin: "50% 50%",
        }}
      />
    );
  };
  const r = edge?.render,
    chat = edge?.chat_box || [0, 0, 140, 104];
  const working = ["thinking", "executing"].includes(edge?.activity);
  const caption = settings.quiet
    ? "聊聊…"
    : working
      ? "Token 来！"
      : aside || "哦鲸鲸…";
  const mini = edge?.mini_visible !== false;
  return (
    <div
      className="edge-viewport"
      data-mode={edge?.mode || "HIDDEN"}
      data-mini-glass={edge?.mini_glass === true}
      data-working={working}
      data-anchor={edge?.anchor}
      data-direction={edge?.direction}
      data-reduce={systemReduce || !settings.animation || settings.quiet}
      style={{ width: W, height: H, transform: `scale(${settings.size})` }}
    >
      <button
        className="edge-body"
        aria-label={`${asset?.label || "角色"}，点击身体换边，拖动移动`}
        onClick={(e) => {
          if (e.detail === 0) act("relocate");
        }}
        onContextMenu={(e) => e.preventDefault()}
      >
        <span className="edge-art-clip" style={{ opacity: r?.opacity ?? 0 }}>
          {art(r, "edge-main")}
        </span>
        {art(r?.tail, "edge-tail")}
        {r?.water > 0 && (
          <svg
            className="edge-water"
            viewBox="0 0 240 20"
            style={{ opacity: r.water }}
            aria-hidden="true"
          >
            <path
              d="M28 12 Q66 2 105 12 M110 12 Q153 1 199 12"
              fill="none"
              stroke="#7dc5e7"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        )}
      </button>
      <button
        className="edge-chat-entry edge-thought"
        aria-label="哦鲸鲸，打开聊天与宠物设置"
        aria-hidden={!mini}
        tabIndex={mini ? 0 : -1}
        style={{
          left: chat[0],
          top: chat[1],
          width: chat[2],
          height: chat[3],
          opacity: mini ? 1 : 0,
          pointerEvents: mini ? "auto" : "none",
        }}
        onClick={(e) => {
          if (e.detail === 0) act("chat");
        }}
      >
        <svg viewBox="0 0 140 104" aria-hidden="true">
          <g
            transform={`${edge?.thought_left ? "translate(140 0) scale(-1 1)" : ""} ${edge?.thought_up ? "translate(0 104) scale(1 -1)" : ""}`}
          >
            <ellipse cx="70" cy="38" rx="66" ry="35" />
            <circle cx="99" cy="87" r="6" />
            <circle cx="116" cy="99" r="3" />
          </g>
        </svg>
        <span
          className="edge-thought-label"
          data-up={edge?.thought_up}
          data-long={caption.length > 8}
        >
          {caption}
        </span>
      </button>
      {(!pack?.url || r?.source === "pending" || error) && (
        <span className="edge-pending">{error || "新版角色姿态待导入"}</span>
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { call } from "../bridge";
import type { PetSettings } from "./policy";
import { petEvents } from "./events";
import { measurePetAnimation } from "./animationProbe";
import type { EdgePack, EdgePresentation, PetAsset, RenderPart } from "./types";
const W = 240,
  H = 220;
export default function EdgeCharacter({
  asset,
  settings,
  systemReduce,
  nativePointer,
  aside,
}: {
  asset: PetAsset | null;
  settings: PetSettings;
  systemReduce: boolean;
  nativePointer: boolean;
  aside: string;
}) {
  const [edge, setEdge] = useState<EdgePresentation | null>(null),
    [pack, setPack] = useState<EdgePack | undefined>(),
    [error, setError] = useState("");
  const pointer = useRef<{ x: number; y: number; dragged: boolean } | null>(
    null,
  );
  useEffect(() => setPack(asset?.edge), [asset]);
  useEffect(() => {
    const events = petEvents((error) => setError(String(error)));
    let stopProbe = () => {};
    void events.on<EdgePresentation>("pet-edge", setEdge);
    void events.on<EdgePack>("pet-edge-asset", setPack);
    void events.on("pet-measure-animation", () => {
      stopProbe();
      stopProbe = measurePetAnimation((error) => setError(String(error)));
    });
    void call<EdgePresentation>("pet_edge", { action: "state" })
      .then(setEdge)
      .catch((e) => setError(String(e)));
    return () => {
      events.close();
      stopProbe();
    };
  }, []);
  const act = (action: string) =>
    void call("pet_edge", { action }).catch((e) => setError(String(e)));
  const sourceFor = (name: string) =>
    name === "legacy" ? asset : name === "edge" ? pack : pack?.extras?.[name];
  const art = (part: RenderPart | null | undefined, cls: string) => {
    if (!part) return null;
    const src = sourceFor(part.source);
    if (!src?.url || !src.width || !src.height) return null;
    const r = part.rect,
      b = part.box,
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
          opacity: part.opacity,
          backgroundImage: `url(${src.url})`,
          backgroundSize: `${src.width * scale}px ${src.height * scale}px`,
          backgroundPosition: `${-r[0] * scale}px ${-r[1] * scale}px`,
          transform: `rotate(${part.angle}deg)`,
          transformOrigin: "50% 50%",
        }}
      />
    );
  };
  const r = edge?.render,
    chat = edge?.chat_box || [0, 0, 140, 104];
  const working =
    edge?.activity === "thinking" || edge?.activity === "executing";
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
      data-reduce={
        systemReduce ||
        !settings.animation ||
        settings.quiet ||
        edge?.motion === false
      }
      style={{ width: W, height: H, transform: `scale(${settings.size})` }}
    >
      <button
        className="edge-body"
        aria-label={`${asset?.label || "角色"}，点击身体换边，拖动移动`}
        onPointerDown={(e) => {
          if (!nativePointer && e.button === 0)
            pointer.current = { x: e.clientX, y: e.clientY, dragged: false };
        }}
        onPointerMove={(e) => {
          const gesture = pointer.current;
          if (nativePointer || !gesture || gesture.dragged || e.buttons !== 1)
            return;
          if (Math.hypot(e.clientX - gesture.x, e.clientY - gesture.y) < 5)
            return;
          gesture.dragged = true;
          void call("pet_action", { action: "drag" }).catch((error) =>
            setError(String(error)),
          );
        }}
        onClick={(e) => {
          if (e.detail === 0 || (!nativePointer && !pointer.current?.dragged))
            act("relocate");
          pointer.current = null;
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          if (!nativePointer) act("chat");
        }}
      >
        <span className="edge-art-clip" style={{ opacity: r?.opacity ?? 0 }}>
          {art(r, "edge-main")}
        </span>
        {art(r?.tail, "edge-tail")}
        {r && r.water > 0 && (
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
          if (e.detail === 0 || !nativePointer) act("chat");
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

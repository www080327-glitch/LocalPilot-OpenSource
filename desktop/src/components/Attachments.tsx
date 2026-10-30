import { useEffect, useState, useRef } from "react";
import { FileText, X, Image as ImageIcon } from "lucide-react";
import { call, desktop } from "../bridge";
import { listen } from "@tauri-apps/api/event";
import type { Json } from "../domain";
import { Modal } from "./Modal";
function locationOf(a: Json) {
  return (
    [
      a.page && `第 ${a.page} 页`,
      a.slide && `第 ${a.slide} 张幻灯片`,
      a.sheet && `${a.sheet}${a.cell ? ` · ${a.cell}` : ""}`,
      a.paragraph && `段落 ${a.paragraph}`,
      a.line && `第 ${a.line} 行`,
      a.member && a.member,
      a.row && `行 ${a.row}`,
      a.column && `列 ${a.column}`,
    ]
      .filter(Boolean)
      .join(" · ") || "文档"
  );
}
const documentStatuses: Record<string, string> = {
  queued: "待解析",
  processing: "解析中",
  complete: "已解析",
  partial: "部分已解析",
  unsupported: "格式暂不支持",
  failed: "解析失败",
};
export function useAttachments(onError: (e: unknown) => void) {
  const [files, setFiles] = useState<Json[]>([]);
  useEffect(() => {
    if (!desktop) return;
    let stop: (() => void) | undefined;
    let stopError: (() => void) | undefined;
    let cancelled = false;
    listen<Json[]>("localpilot-files", (e) =>
      setFiles((old) => [...old, ...e.payload]),
    ).then((f) => {
      if (cancelled) f();
      else stop = f;
    });
    listen<string>("localpilot-files-error", (e) =>
      onError(Error(e.payload)),
    ).then((f) => {
      if (cancelled) f();
      else stopError = f;
    });
    return () => {
      cancelled = true;
      stop?.();
      stopError?.();
    };
  }, []);
  async function pick() {
    try {
      setFiles((old) => old);
      const next = await call<Json[]>("pick_attachments");
      setFiles((old) => [...old, ...next]);
    } catch (e) {
      onError(e);
    }
  }
  async function paste(list: FileList) {
    try {
      for (const f of Array.from(list)) {
        if (f.size > 8 * 1024 ** 2)
          throw Error("粘贴文件超过 8 MB，请使用文件选择器添加。");
        const next = await call<Json[]>("stage_attachment", {
          name: f.name,
          bytes: Array.from(new Uint8Array(await f.arrayBuffer())),
        });
        setFiles((old) => [...old, ...next]);
      }
    } catch (e) {
      onError(e);
    }
  }
  async function folder() {
    try {
      const next = await call<Json[]>("pick_attachment_folder");
      setFiles((old) => [...old, ...next]);
    } catch (e) {
      onError(e);
    }
  }
  async function remove(id: string) {
    try {
      await call("remove_attachment", { id });
      setFiles((old) => old.filter((f) => f.id !== id));
    } catch (e) {
      onError(e);
    }
  }
  return { files, setFiles, pick, paste, folder, remove };
}
function Thumbnail({ file, onOpen }: { file: Json; onOpen: () => void }) {
  const ref = useRef<HTMLButtonElement>(null),
    [url, setUrl] = useState("");
  useEffect(() => {
    let live = true;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        observer.disconnect();
        call<Json>("attachment_thumbnail", { id: file.id })
          .then((v) => {
            if (live) setUrl(v.url);
          })
          .catch(() => {});
      }
    });
    if (ref.current) observer.observe(ref.current);
    return () => {
      live = false;
      observer.disconnect();
    };
  }, [file.id]);
  return (
    <button
      ref={ref}
      className="attachment-thumb"
      aria-label={`预览 ${file.name}`}
      onClick={onOpen}
    >
      {url ? (
        <img src={url} alt={file.name} loading="lazy" />
      ) : (
        <ImageIcon size={22} />
      )}
    </button>
  );
}
export function AttachmentCards({
  files,
  onRemove,
  onError,
}: {
  files: Json[];
  onRemove: (id: string) => void;
  onError: (e: unknown) => void;
}) {
  const [expanded, setExpanded] = useState<Json | null>(null),
    [fit, setFit] = useState(true),
    [zoom, setZoom] = useState(1);
  async function preview(file: Json) {
    try {
      const value = await call<Json>("attachment_preview", { id: file.id });
      setExpanded({ ...file, ...value });
      setFit(true);
      setZoom(1);
    } catch (e) {
      onError(e);
    }
  }
  return (
    <>
      <div className="attachment-cards">
        {files.map((f) => (
          <article
            className="attachment-card"
            key={f.id}
            tabIndex={0}
            title="双击可在 Finder 中显示原文件"
            onDoubleClick={() =>
              call("open_attachment", { id: f.id }).catch(onError)
            }
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.target === e.currentTarget) {
                e.stopPropagation();
                call("open_attachment", { id: f.id }).catch(onError);
              }
            }}
          >
            {/\.(png|jpe?g|webp|gif)$/i.test(f.name) ? (
              <Thumbnail file={f} onOpen={() => preview(f)} />
            ) : (
              <button
                className="attachment-thumb"
                aria-label={`预览 ${f.name}`}
                onClick={() => preview(f)}
              >
                <FileText size={22} />
              </button>
            )}
            <div>
              <strong title={f.name}>{f.name}</strong>
              <small>
                {(f.size / 1024).toFixed(1)} KB ·{" "}
                {f.status === "importing"
                  ? "正在导入"
                  : f.status === "error"
                    ? "导入未确认"
                    : "已选择"}
              </small>
              {f.selection_skipped?.length > 0 && (
                <small>已跳过 {f.selection_skipped.length} 个受保护来源</small>
              )}
            </div>
            <button
              className="icon-btn"
              aria-label={`移除 ${f.name}`}
              onClick={() => onRemove(f.id)}
            >
              <X size={13} />
            </button>
          </article>
        ))}
      </div>
      {files.some((f) => /\.(png|jpe?g|webp|gif)$/i.test(f.name)) && (
        <p className="micro muted">
          <ImageIcon size={12} />
          图片作为文件提供；当前任务未提交视觉输入，不代表模型已理解图片。
        </p>
      )}
      {expanded && (
        <Modal
          title={expanded.url ? "图片预览" : "附件预览"}
          onClose={() => setExpanded(null)}
          wide
        >
          {!expanded.url ? (
            <pre className="document-excerpt">
              {expanded.text}
              {expanded.truncated ? "\n（预览已截断，原件保留）" : ""}
            </pre>
          ) : (
            <>
              <div className="image-zoom-controls">
                <button className="secondary" onClick={() => setFit(true)}>
                  适应窗口
                </button>
                <button
                  className="secondary"
                  onClick={() => {
                    setFit(false);
                    setZoom(1);
                  }}
                >
                  实际大小
                </button>
                <button
                  className="secondary"
                  aria-label="缩小图片"
                  onClick={() => {
                    setFit(false);
                    setZoom((z) => Math.max(0.25, z - 0.25));
                  }}
                >
                  −
                </button>
                <span>{fit ? "适应窗口" : `${Math.round(zoom * 100)}%`}</span>
                <button
                  className="secondary"
                  aria-label="放大图片"
                  onClick={() => {
                    setFit(false);
                    setZoom((z) => Math.min(4, z + 0.25));
                  }}
                >
                  +
                </button>
              </div>
              <div className="image-viewport">
                <img
                  className="attachment-expanded"
                  style={
                    fit
                      ? {}
                      : {
                          maxWidth: "none",
                          maxHeight: "none",
                          width: expanded.width * zoom,
                          height: expanded.height * zoom,
                        }
                  }
                  src={expanded.url}
                  alt={expanded.name}
                />
              </div>
            </>
          )}
        </Modal>
      )}
    </>
  );
}

export function DocumentPanel({
  sessionId,
  refresh,
  onError,
}: {
  sessionId: string | null;
  refresh?: string;
  onError: (e: unknown) => void;
}) {
  const [files, setFiles] = useState<Json[]>([]),
    [preview, setPreview] = useState<Json | null>(null),
    [busy, setBusy] = useState(false);
  const [page, setPage] = useState({
    cursor: 0,
    next: 0,
    count: 0,
    more: false,
  });
  async function operation(operation: string, args: Json = {}) {
    return call<Json>("product_control", {
      operation: "documents",
      args: { operation, session_id: sessionId, ...args },
    });
  }
  async function load(cursor = 0) {
    if (!sessionId) return;
    const value = await operation("list", { cursor, limit: 100 });
    setFiles(value.files);
    setPage({
      cursor,
      next: value.next_cursor || cursor + value.files.length,
      count: value.count ?? value.files.length,
      more: !!value.has_more,
    });
  }
  useEffect(() => {
    setFiles([]);
    setPreview(null);
    if (sessionId) void load().catch(onError);
  }, [sessionId, refresh]);
  useEffect(() => {
    const handler = (event: Event) => {
      const citation = (event as CustomEvent).detail?.citation;
      const m =
        typeof citation === "string" &&
        /^lpdoc:(att_[0-9a-f]{32}):(\d+):[0-9a-f]{64}$/.exec(citation);
      if (!m || !sessionId) return;
      void operation("read", {
        attachment_id: m[1],
        cursor: Number(m[2]) - 1,
        limit: 1,
      })
        .then((value) => {
          if (value.nodes[0]?.citation !== citation)
            throw Error("引用与实际读取的来源不匹配");
          setPreview(value);
        })
        .catch(onError);
    };
    window.addEventListener("localpilot-document-reference", handler);
    return () =>
      window.removeEventListener("localpilot-document-reference", handler);
  }, [sessionId]);
  async function show(file: Json) {
    setBusy(true);
    try {
      if (file.status === "queued")
        await operation("process", { attachment_id: file.id });
      setPreview(
        await operation("read", { attachment_id: file.id, limit: 12 }),
      );
      await load();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  async function revoke(file: Json) {
    try {
      await operation("revoke", { attachment_id: file.id });
      setPreview(null);
      await load();
    } catch (e) {
      onError(e);
    }
  }
  if (!files.length) return null;
  return (
    <div className="session-documents" aria-label="会话附件">
      <details>
        <summary>{page.count} 个会话附件 · 默认本地解析</summary>
        {files.map((f) => (
          <article key={f.id} className="attachment-card">
            <button
              disabled={busy}
              className="secondary"
              onClick={() => void show(f)}
              aria-label={`读取文档 ${f.name}`}
            >
              {f.name}
            </button>
            <small>
              {f.detected_format || "格式待检测"} ·{" "}
              {documentStatuses[f.status] || f.status} · {f.parsed_nodes}{" "}
              个结构片段
            </small>
            {f.cloud_uploaded === true && <small>已向云端发送派生图片</small>}
            {f.cloud_egress_status === "unknown" && (
              <small>最近一次云端发送结果未确认</small>
            )}
            <button
              className="icon-btn"
              aria-label={`撤销附件 ${f.name}`}
              onClick={() => void revoke(f)}
            >
              <X size={13} />
            </button>
          </article>
        ))}
        {(page.more || page.cursor > 0) && (
          <div>
            <button
              className="secondary"
              disabled={!page.cursor}
              onClick={() =>
                void load(Math.max(0, page.cursor - 100)).catch(onError)
              }
            >
              上一组附件
            </button>
            <button
              className="secondary"
              disabled={!page.more}
              onClick={() => void load(page.next).catch(onError)}
            >
              下一组附件
            </button>
          </div>
        )}
        <p className="micro muted">
          附件随会话保留，默认 7
          天。撤销后禁止新的读取与出站；原件保留在受控缓存中。
        </p>
      </details>
      {preview && (
        <Modal title="文档来源预览" onClose={() => setPreview(null)} wide>
          <p>
            {preview.document.name} ·{" "}
            {documentStatuses[preview.document.status] ||
              preview.document.status}
          </p>
          {preview.nodes.map((n: Json) => (
            <article key={n.citation}>
              <small>{locationOf(n.anchor)}</small>
              <pre className="document-excerpt">
                {n.text || JSON.stringify(n.properties)}
              </pre>
              <details>
                <summary>引用标识</summary>
                <code>{n.citation}</code>
              </details>
            </article>
          ))}
          {preview.has_more && (
            <button
              className="secondary"
              onClick={() =>
                void operation("read", {
                  attachment_id: preview.document.id,
                  cursor: preview.next_cursor,
                  limit: 12,
                })
                  .then(setPreview)
                  .catch(onError)
              }
            >
              下一组片段
            </button>
          )}
        </Modal>
      )}
    </div>
  );
}

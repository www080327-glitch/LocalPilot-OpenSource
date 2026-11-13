import { Cloud, Monitor, Layers } from "lucide-react";
import type { CollaborationUsage } from "../collaboration";

export function CollaborationStrip({
  usage,
  open,
}: {
  usage: CollaborationUsage;
  open: () => void;
}) {
  const total = usage.localRequests + usage.cloudRequests;
  const local = total ? Math.round((usage.localRequests / total) * 100) : 0;
  return (
    <button className="collaboration-strip" onClick={open} aria-label="查看本地云端模型与子代理调用">
      <span className="collaboration-inline">
        <Layers size={14} />
        {total
          ? `本地 ${local}% · 云端 ${100 - local}%`
          : "本地/云端：暂无真实调用记录"}
        {usage.subagents.length > 0 && ` · 子代理 ${usage.subagents.length}`}
      </span>
      {total > 0 && (
        <span className="collaboration-meter" aria-hidden="true">
          <span style={{ width: `${local}%` }} />
        </span>
      )}
      <span className="collaboration-detail">查看调用详情</span>
    </button>
  );
}

export function CollaborationPanel({ usage }: { usage: CollaborationUsage }) {
  const total = usage.localRequests + usage.cloudRequests;
  return (
    <section className="inspector-section collaboration-panel">
      <h3><Layers size={15} /> 实际模型请求</h3>
      <p className="micro muted">占比按事件中真实发起的模型请求次数统计，不代表 Token、耗时或费用；断线或事件窗口截断时可能不完整。</p>
      {total ? (
        <div className="collaboration-summary">
          <span><Monitor size={15} /> 本地 {usage.localRequests} 次（{Math.round(usage.localRequests * 100 / total)}%）</span>
          <span><Cloud size={15} /> 云端 {usage.cloudRequests} 次（{Math.round(usage.cloudRequests * 100 / total)}%）</span>
        </div>
      ) : <p className="quiet-empty">当前事件窗口没有可归属的模型请求记录。</p>}
      {usage.unknownRequests > 0 && <p className="micro muted">另有 {usage.unknownRequests} 次请求未报告来源，未计入占比。</p>}
      <h3><Layers size={15} /> 子代理 {usage.subagents.length}</h3>
      {usage.subagents.length ? usage.subagents.map((agent) => (
        <details key={agent.id} className="collaboration-agent">
          <summary><strong>{agent.model}</strong><small>{agent.backend} · {agent.status}</small></summary>
          <dl>
            <dt>子代理 ID</dt><dd>{agent.id}</dd>
            <dt>提供方</dt><dd>{agent.provider}</dd>
            <dt>模型</dt><dd>{agent.model}</dd>
            <dt>执行层级</dt><dd>{agent.tier}</dd>
            <dt>可见请求</dt><dd>{agent.requests} 次</dd>
          </dl>
        </details>
      )) : <p className="micro muted">没有真实 SubagentStarted 事件。普通模型切换不会冒充子代理。</p>}
    </section>
  );
}

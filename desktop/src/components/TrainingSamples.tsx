import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";

export type TrainingRequest = (command: string, args?: Json) => Promise<Json>;

const companionRequest: TrainingRequest = (command, args = {}) =>
  call<Json>("companion", { command, args });

const purposeNames: Record<string, string> = {
  greeting: "问候",
  activity_qa: "活动问答",
  handoff: "任务交接",
};

async function trainingCommand(
  request: TrainingRequest,
  command: string,
  args: Json = {},
) {
  const result = await request(command, args);
  if (result.status !== "ok")
    throw Error(
      result.text || result.error || result.reason || "样本操作未完成",
    );
  return result;
}

export function TrainingReview({
  answerId,
  request = companionRequest,
  onSaved,
  onClose,
}: {
  answerId: string;
  request?: TrainingRequest;
  onSaved?: () => void;
  onClose: () => void;
}) {
  const [candidate, setCandidate] = useState<Json | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let disposed = false;
    setCandidate(null);
    setLoading(true);
    setError("");
    setSaved(false);
    void trainingCommand(request, "training_review", { answer_id: answerId })
      .then((result) => {
        if (disposed) return;
        setCandidate(result.candidate);
        setQuestion(result.candidate.question);
        setAnswer(result.candidate.answer);
      })
      .catch((error) => {
        if (!disposed) setError(String(error));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [answerId, request]);

  async function save() {
    if (!candidate) return;
    setBusy(true);
    setError("");
    try {
      await trainingCommand(request, "training_example_add", {
        answer_id: answerId,
        question: question.trim(),
        answer: answer.trim(),
        purpose: candidate.purpose,
      });
      setSaved(true);
      onSaved?.();
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="training-review" aria-label="审阅训练样本">
      <h4>审阅为训练样本</h4>
      <p className="muted">
        核对并修改问答后再保存。来源由 Companion 重新核验；保存不会启动训练。
      </p>
      {loading && <p role="status">正在读取已显示问答及当前可用来源…</p>}
      {candidate && (
        <>
          <p>
            样本用途：{purposeNames[candidate.purpose] || candidate.purpose}
          </p>
          <label>
            问题
            <textarea
              aria-label="训练样本问题"
              value={question}
              disabled={busy || saved}
              onChange={(event) => setQuestion(event.target.value)}
              rows={2}
            />
          </label>
          <label>
            已审阅回答
            <textarea
              aria-label="训练样本回答"
              value={answer}
              disabled={busy || saved}
              onChange={(event) => setAnswer(event.target.value)}
              rows={5}
            />
          </label>
          <details>
            <summary>关联来源（{candidate.sources.length}）</summary>
            {candidate.sources.length ? (
              candidate.sources.map((source: Json) => (
                <div className="training-source" key={source.id}>
                  <strong>{source.source_reference || source.kind}</strong>
                  <p>{source.summary}</p>
                  <p className="micro muted">
                    {source.evidence_type} · {source.evidence_epistemic}
                  </p>
                  {source.locator && (
                    <code>{JSON.stringify(source.locator)}</code>
                  )}
                </div>
              ))
            ) : (
              <p className="muted">此问候样本没有活动来源关联。</p>
            )}
          </details>
          <button
            className="primary"
            disabled={busy || saved || !question.trim() || !answer.trim()}
            onClick={() => void save()}
          >
            {busy ? "正在保存…" : saved ? "已保存审阅样本" : "保存已审阅样本"}
          </button>
        </>
      )}
      {saved && <p role="status">样本已保存；模型训练尚未运行。</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <button className="text-btn" disabled={busy} onClick={onClose}>
        {saved ? "关闭审阅" : "取消审阅"}
      </button>
    </section>
  );
}

export function TrainingSamples() {
  const [candidates, setCandidates] = useState<Json[]>([]);
  const [examples, setExamples] = useState<Json[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [exported, setExported] = useState<Json | null>(null);
  const [heldOut, setHeldOut] = useState(false);

  async function refresh() {
    const [recent, saved] = await Promise.all([
      trainingCommand(companionRequest, "training_candidates", { limit: 20 }),
      trainingCommand(companionRequest, "training_examples"),
    ]);
    setCandidates(recent.candidates);
    setExamples(saved.examples);
    setLoaded(true);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="advanced-settings">
      <summary>人工审阅与训练样本</summary>
      <p className="muted">
        从已显示且仍有可用来源的 Companion 回答中选择候选，逐条修改并保存。
        候选列表不会自动成为训练数据。
      </p>
      <button
        className="secondary"
        disabled={!desktop || busy}
        onClick={() => void run(refresh)}
      >
        读取可审阅回答与已保存样本
      </button>
      {loaded && !candidates.length && (
        <p className="muted">
          当前没有可审阅回答。请先向 Companion
          提问；关闭记忆或来源已失效的回答不会列入。
        </p>
      )}
      {candidates.map((candidate) => (
        <div className="training-candidate" key={candidate.answer_id}>
          <p>{candidate.question}</p>
          <small>
            {purposeNames[candidate.purpose] || candidate.purpose} ·{" "}
            {candidate.source_count} 个来源
          </small>
          <button
            className="text-btn"
            disabled={busy}
            onClick={() => setReviewing(candidate.answer_id)}
          >
            审阅这条回答
          </button>
        </div>
      ))}
      {reviewing && (
        <TrainingReview
          key={reviewing}
          answerId={reviewing}
          onClose={() => setReviewing(null)}
          onSaved={() => void run(refresh)}
        />
      )}
      <h4>
        已明确保存的样本{loaded ? `（${examples.length}）` : " · 尚未读取"}
      </h4>
      {examples.map((example) => (
        <details className="training-example" key={example.id}>
          <summary>
            {purposeNames[example.purpose] || example.purpose} ·{" "}
            {example.available
              ? example.question
              : "来源已不可用，内容不再展示"}
          </summary>
          {example.available && (
            <p className="training-answer">{example.answer}</p>
          )}
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await trainingCommand(
                  companionRequest,
                  "training_example_delete",
                  { id: example.id },
                );
                setNotice(
                  "样本已移除，不会进入后续导出。已有导出文件需另行处理。",
                );
                await refresh();
              })
            }
          >
            删除此审阅样本
          </button>
        </details>
      ))}
      <p className="muted">
        导出按独立来源划分训练与验证数据。导出文件包含已审阅的私人文本；
        撤销来源或删除样本不会自动删除此前导出的独立文件。
      </p>
      <label>
        <input
          type="checkbox"
          checked={heldOut}
          disabled={busy}
          onChange={(event) => setHeldOut(event.target.checked)}
        />
        保留独立测试集（至少 3 组来源）
      </label>
      <button
        className="secondary"
        disabled={!desktop || busy}
        onClick={() =>
          void run(async () => {
            setExported(null);
            setExported(
              await trainingCommand(companionRequest, "training_export", {
                test_fraction: heldOut ? 0.2 : 0,
              }),
            );
            setNotice("已导出人工审阅样本；未启动模型训练。");
          })
        }
      >
        导出已审阅样本
      </button>
      {exported && (
        <>
          {exported.counts && (
            <p role="status">
              训练 {exported.counts.train ?? 0} 条 · 验证{" "}
              {exported.counts.valid ?? 0} 条
              {exported.counts.test !== undefined
                ? ` · 独立测试 ${exported.counts.test} 条`
                : " · 未保留独立测试集"}
            </p>
          )}
          <pre className="json">{JSON.stringify(exported, null, 2)}</pre>
        </>
      )}
      {busy && <p role="status">正在读取或保存样本…</p>}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </details>
  );
}

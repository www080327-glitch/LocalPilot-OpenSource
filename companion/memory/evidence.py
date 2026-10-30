"""Evidence identity is host metadata, never a model's assertion of truth."""
import re

EVIDENCE_TYPES = {"OBSERVED", "USER_CONFIRMED", "MODEL_INFERRED", "EXTERNAL_SOURCE", "UNKNOWN"}


def is_question(text):
    text = text.strip()
    return bool(re.search(r"[?？]|(?:吗|么|是否|能否|可否|为什么|怎么|多少|谁是|是什么)|^(?:what|why|how|who|when|where|can|could|would|is|are|do|does)\b", text, re.I))


def evidence_type(source, kind, epistemic="factual", text="", evidence=None):
    if epistemic in {"inferred", "inference", "reflection"} or source.startswith(("model", "companion_model", "companion_reflection")):
        return "MODEL_INFERRED"
    if source == "explicit_user_statement" and kind in {"user_fact", "preference", "reminder"}:
        return "UNKNOWN" if kind == "user_fact" and is_question(text) else "USER_CONFIRMED"
    if source == "user_chat":
        return "UNKNOWN"  # Observing a question never confirms its premise.
    if source == "localpilot" and kind == "task_result":
        return "MODEL_INFERRED"  # Task state is separate from its generated answer.
    if (evidence or {}).get("epistemic") in {"reported", "inferred"}:
        return "MODEL_INFERRED"
    if source in {"document_extractor", "external_source"}:
        return "EXTERNAL_SOURCE"
    if source in {"accessibility", "nsworkspace", "file_observer", "session", "directory_relation"}:
        return "OBSERVED"
    return "UNKNOWN"


def describe(row):
    return evidence_type(row.get("source", ""), row.get("type", row.get("kind", "")),
                         row.get("epistemic", "factual"), row.get("summary", ""), row.get("evidence"))

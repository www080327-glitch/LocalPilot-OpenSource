"""Small finite schemas, strict parsing and at most one fresh model repair.

Constrained output proves syntax, never correctness or calibrated confidence.
The finite language is deliberately small enough to constrain without a new dependency.
"""
import json
import math


LABELS = {
    "active": ("quiet", "notify", "ask-help", "escalate"),
    "route": ("local", "agent"),
    "support": ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNVERIFIED", "CONTRADICTED"),
}
KEYS = {"active": "action", "route": "route", "support": "support"}
CONFIDENCES = (0.0, 0.5, 0.9, 0.95, 1.0)


def language(schema):
    key = KEYS[schema]
    return [json.dumps({key: label, "confidence": confidence}, separators=(",", ":"))
            for label in LABELS[schema] for confidence in CONFIDENCES]


def json_schema(schema):
    return {"type": "object", "properties": {
        KEYS[schema]: {"type": "string", "enum": list(LABELS[schema])},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
        "required": [KEYS[schema], "confidence"], "additionalProperties": False}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse(result, schema, legacy_active=False):
    if not isinstance(result, dict) or result.get("status") != "ok":
        return None
    text = result.get("text")
    if not isinstance(text, str) or not 0 < len(text) <= 4096:
        return None
    try:
        obj = json.loads(text, object_pairs_hook=_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        if not isinstance(obj, dict):
            return None
        # Explicit V0 compatibility schema. No missing-field inference or text salvage.
        if legacy_active and schema == "active" and set(obj) == {"notify", "confidence", "understood"}:
            if type(obj["notify"]) is not bool or type(obj["understood"]) is not bool:
                return None
            obj = {"action": "ask-help" if obj["notify"] and obj["understood"] else "quiet",
                   "confidence": obj["confidence"]}
        if set(obj) != {KEYS[schema], "confidence"}:
            return None
        if type(obj[KEYS[schema]]) is not str or obj[KEYS[schema]] not in LABELS[schema]:
            return None
        confidence = obj["confidence"]
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return None
        return obj
    except (ValueError, TypeError, KeyError):
        return None


def decide(model, messages, schema, max_tokens=96, repairs=1, legacy_active=False):
    if repairs not in (0, 1):
        raise ValueError("Only zero or one repair is allowed")
    attempts = []
    prompt = list(messages)
    for attempt in range(repairs + 1):
        result = model.complete(prompt, max_tokens=max_tokens, schema=schema)
        decision = parse(result, schema, legacy_active)
        attempts.append({"result": result, "valid": decision is not None})
        if decision is not None:
            return {"decision": decision, "attempts": attempts, "status": "valid"}
        if attempt < repairs:
            # Do not invent defaults or patch malformed JSON locally.
            prompt = list(messages) + [{"role": "user", "content":
                "上次输出不符合契约。重新判断原问题，只返回一个完整对象。契约：" +
                json.dumps(json_schema(schema), ensure_ascii=False)}]
    return {"decision": None, "attempts": attempts, "status": "invalid_fail_closed"}


class TokenLanguage:
    """Token trie for a finite set of complete JSON strings, including EOS only at leaves."""
    def __init__(self, sequences, eos):
        self.root = {}
        self.eos = set(eos)
        if not sequences or not self.eos:
            raise ValueError("Empty constrained language")
        for sequence in sequences:
            if not sequence or self.eos.intersection(sequence):
                raise ValueError("Invalid constrained sequence")
            node = self.root
            for token in sequence:
                node = node.setdefault(token, {})
            node[None] = True

    def allowed(self, prefix):
        node = self.root
        for index, token in enumerate(prefix):
            if token in self.eos and None in node:
                # MLX computes one step ahead before yielding the stopping token.
                # Only a terminal EOS may enter this sink; early EOS still fails.
                if all(t in self.eos for t in prefix[index:]):
                    return self.eos
                raise ValueError("Tokens after terminal EOS")
            if token not in node:
                raise ValueError("Output escaped constrained language")
            node = node[token]
        return {k for k in node if k is not None} | (self.eos if None in node else set())


def mlx_processor(tokenizer, schema, max_tokens):
    import mlx.core as mx
    sequences = [tokenizer.encode(text, add_special_tokens=False) for text in language(schema)]
    if max(map(len, sequences)) + 1 > max_tokens:
        raise ValueError("Output budget cannot complete constrained schema")
    trie = TokenLanguage(sequences, tokenizer.eos_token_ids)
    start = None

    def process(tokens, logits):
        nonlocal start
        if start is None:
            # MLX's first processor call includes the remaining prompt tokens.
            start = len(tokens)
        allowed = trie.allowed(tokens[start:].tolist())
        mask = mx.full(logits.shape, float("-inf"))
        ids = mx.array(sorted(allowed))
        mask[..., ids] = logits[..., ids]
        return mask
    return process

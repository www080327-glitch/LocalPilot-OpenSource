"""Token admission for routing; byte accounting in the execution ledger is separate."""
import json
import math


def request_budget(messages, tools, output_tokens, *, tokenizer=None):
    wire = [message.to_dict(include_reasoning=True) for message in messages]
    input_tokens, estimator = _input_tokens(wire, tools, tokenizer)
    margin = max(64, math.ceil(input_tokens * .02))
    return {'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'margin_tokens': margin, 'total_tokens': input_tokens + output_tokens + margin,
            'estimator': estimator, 'measured': estimator == 'backend_chat_template'}


def _input_tokens(messages, tools, tokenizer):
    if tokenizer is not None:
        try:
            args = {'tokenize': True, 'add_generation_prompt': True}
            if tools:
                args['tools'] = tools
            tokens = tokenizer.apply_chat_template(messages, **args)
            # A tokenizer/template mismatch falls back to an explicit estimate.
            if isinstance(tokens, (list, tuple)) and all(type(token) is int for token in tokens):
                return len(tokens), 'backend_chat_template'
        except (ValueError, TypeError, AttributeError, NotImplementedError):
            pass
    text = json.dumps([messages, tools], ensure_ascii=False, separators=(',', ':'))
    ascii_count = sum(char.isascii() for char in text)
    non_ascii_bytes = sum(len(char.encode('utf-8')) for char in text if not char.isascii())
    # Deliberately labeled heuristic, not provider usage or a context-fit guarantee.
    estimate = math.ceil(ascii_count / 3) + non_ascii_bytes + 8 * len(messages)
    return estimate, 'mixed_text_estimate_v1'


def context_tokens(messages, tools, *, tokenizer=None):
    """Context-window estimate in tokens; does not alter byte-denominated ledgers."""
    wire = [message.to_dict(include_reasoning=True) for message in messages]
    return _input_tokens(wire, tools, tokenizer)[0]

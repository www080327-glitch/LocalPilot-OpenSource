"""Provider-owned usage only. Missing cache accounting is not a zero bill."""
def cache_usage(task):
    calls = (task.get("result") or {}).get("model_calls")
    if not isinstance(calls, list) or not calls:
        return {"status":"UNKNOWN", "input_tokens":None, "output_tokens":None,
                "cache_hit_tokens":None, "cache_miss_tokens":None, "cache_hit_ratio":None}
    names = ("input_tokens", "output_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
    valid = all(isinstance(row, dict) and all(type(row.get(k)) is int and row[k]>=0 for k in names)
                and row["input_tokens"]==row["prompt_cache_hit_tokens"]+row["prompt_cache_miss_tokens"] for row in calls)
    if not valid:
        # Independent provider token counters remain useful even when cache
        # accounting is absent. Unknown hits never become zero or a bill.
        known={key:sum(row[key] for row in calls) if all(isinstance(row,dict) and type(row.get(key)) is int and row[key]>=0 for row in calls) else None for key in ("input_tokens","output_tokens")}
        return {"status":"UNKNOWN", **known,
                "cache_hit_tokens":None, "cache_miss_tokens":None, "cache_hit_ratio":None}
    totals={k:sum(row[k] for row in calls) for k in names}
    inputs=totals["input_tokens"]
    return {"status":"PROVIDER_REPORTED", "input_tokens":inputs, "output_tokens":totals["output_tokens"],
            "cache_hit_tokens":totals["prompt_cache_hit_tokens"], "cache_miss_tokens":totals["prompt_cache_miss_tokens"],
            "cache_hit_ratio":totals["prompt_cache_hit_tokens"]/inputs if inputs else None,
            "cost":"UNKNOWN_NOT_INVOICE", "models":list(dict.fromkeys(r.get("reported_model") for r in calls))}

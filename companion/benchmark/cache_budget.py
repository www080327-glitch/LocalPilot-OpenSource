"""Hard, persistent test admission; no paid warmup loop or filler prompts."""
import json
import fcntl
import os
from functools import wraps


def locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        fd=os.open(str(self.path)+".lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"a") as guard:
            fcntl.flock(guard,fcntl.LOCK_EX)
            if self.path.exists():
                if self.path.is_symlink():raise ValueError("Symlink budget file refused")
                self.state=json.loads(self.path.read_text())
            return method(self,*args,**kwargs)
    return call
from pathlib import Path


class CacheTestBudget:
    def __init__(self, path, *, max_calls=2, max_uncached_tokens=32768,
                 max_payload_bytes=16384, max_output_tokens=512, warm_hit_ratio=.99):
        self.path=Path(path)
        self.max_calls=max_calls;self.max_uncached_tokens=max_uncached_tokens
        self.max_payload_bytes=max_payload_bytes;self.max_output_tokens=max_output_tokens
        self.warm_hit_ratio=warm_hit_ratio
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {"calls":0,"reserved_bytes":0,"known_miss_tokens":0,"outputs":0,"observed":[],"halt_reason":None}

    def save(self):
        temporary=self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state,indent=2)+"\n");temporary.chmod(0o600)
        temporary.replace(self.path)

    @locked
    def admit(self, payload):
        size=len(json.dumps(payload,ensure_ascii=False).encode())
        reason=self.state["halt_reason"]
        if not reason:
            reason=("call_limit" if self.state["calls"]>=self.max_calls else
                    "payload_byte_limit" if size>self.max_payload_bytes else
                    "output_limit" if payload.get("max_tokens",self.max_output_tokens+1)>self.max_output_tokens else
                    "uncached_reservation_limit" if self.state["known_miss_tokens"]+self.state["reserved_bytes"]+size>self.max_uncached_tokens else None)
        if reason:
            self.state["halt_reason"]=reason;self.save();raise RuntimeError("Cloud acceptance stopped: "+reason)
        # UTF-8 bytes conservatively reserve possible uncached input tokens.
        # Reservations survive process restart and unknown/partial responses.
        self.state["calls"]+=1;self.state["reserved_bytes"]+=size;self.save()

    @locked
    def observe(self, task_id, usage, request_bytes=0):
        if task_id in self.state["observed"]:
            return
        self.state["observed"].append(task_id)
        reason=None
        if usage.get("status")!="PROVIDER_REPORTED":
            reason="cache_usage_unknown"
        else:
            self.state["known_miss_tokens"]+=usage["cache_miss_tokens"]
            self.state["outputs"]+=usage["output_tokens"]
            # Only a caller with an exact matching reservation may release it.
            self.state["reserved_bytes"]=max(0,self.state["reserved_bytes"]-request_bytes)
            if self.state["known_miss_tokens"]>self.max_uncached_tokens:
                reason="uncached_token_limit"
            elif len(self.state["observed"])>1 and (usage.get("cache_hit_ratio") or 0)<self.warm_hit_ratio:
                reason="warm_cache_below_target"
        if reason:self.state["halt_reason"]=reason
        self.save()
        return reason

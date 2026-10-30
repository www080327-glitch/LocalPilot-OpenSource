"""Portable HTTP CLI and newline JSON-RPC MCP stdio adapter (no control token)."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError
if __package__:
    from .sdk import Client
else:
    from sdk import Client

TOOLS = [
    {"name": "localpilot_submit", "description": "Submit once using a stable idempotency key; inspect task_outcome for host acceptance, not just turn completion.", "inputSchema": {"type": "object", "properties": {"input": {"type": "string"}, "idempotency_key": {"type": "string"}, "session_id": {"type": "string"}, "model": {"type": "string"}, "timeout_seconds": {"type": "number"}}, "required": ["input", "idempotency_key"], "additionalProperties": False}},
    {"name": "localpilot_status", "description": "Get authoritative state, receipts, verification and required_action.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
    {"name": "localpilot_continue", "description": "Resume a checkpoint with the current ticket; server operator scope is required. Does not approve model output.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "action_id": {"type": "string"}}, "required": ["task_id", "action_id"], "additionalProperties": False}},
    {"name": "localpilot_cancel", "description": "Request cooperative cancellation; inspect final receipts afterward.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
]

TOOLS += [
 {"name":"localpilot_capabilities","description":"Discover service API, authenticated identity, configured tool/workspace ceilings and routes before delegation.","inputSchema":{"type":"object","properties":{},"required":[],"additionalProperties":False}},
 {"name":"localpilot_result","description":"Retrieve full authoritative snapshot including receipts, execution, delivery and verification; no inference of success.","inputSchema":{"type":"object","properties":{"task_id":{"type":"string"}},"required":["task_id"],"additionalProperties":False}},
 {"name":"localpilot_events","description":"Read a bounded batch of actual SSE progress events after a cursor; reconnect with the same task ID and cursor.","inputSchema":{"type":"object","properties":{"task_id":{"type":"string"},"after":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":100}},"required":["task_id"],"additionalProperties":False}},
]
next(t for t in TOOLS if t['name']=='localpilot_capabilities')['inputSchema']['properties']['session_id']={'type':'string'}
for tool in TOOLS:
 tool['annotations']={'readOnlyHint':tool['name'] in {'localpilot_capabilities','localpilot_status','localpilot_events','localpilot_result'},'destructiveHint':tool['name']=='localpilot_submit','idempotentHint':tool['name']!='localpilot_continue','openWorldHint':tool['name']=='localpilot_submit'}
for prop in ('origin_agent','parent_task_id'):
 TOOLS[0]['inputSchema']['properties'][prop]={'type':'string','maxLength':128}
TOOLS[0]['inputSchema']['properties']['max_output_tokens']={'type':'integer','minimum':1}

def validate(schema, args):
    import math
    if not isinstance(args,dict) or set(args)-schema['properties'].keys() or set(schema.get('required',[]))-args.keys():
        raise ValueError('Invalid adapter arguments')
    for k,v in args.items():
        field=schema['properties'][k];kind=field.get('type')
        if kind=='string' and (not isinstance(v,str) or len(v)>field.get('maxLength',1048576)):raise ValueError('Invalid string field')
        if kind=='integer' and type(v) is not int:raise ValueError('Expected integer')
        if kind=='number' and (type(v) not in {int,float} or not math.isfinite(v)):raise ValueError('Expected finite number')
        if kind in {'integer','number'} and not field.get('minimum',-1e100)<=v<=field.get('maximum',1e100):raise ValueError('Number out of bounds')


def invoke(client, name, args):
    schema = next((t["inputSchema"] for t in TOOLS if t["name"] == name), None)
    if schema is None or not isinstance(args, dict) or set(args) - schema["properties"].keys() or set(schema["required"]) - args.keys():
        raise ValueError("Invalid adapter operation or arguments")
    validate(schema,args)
    if name == "localpilot_capabilities":
        result={"health":client.request("/healthz"),"registry":client.request("/localpilot/v1/model-registry")}
        if args.get("session_id") or getattr(client,"authorized_session",None):
            from urllib.parse import quote
            result["session"]=client.request("/localpilot/v1/sessions/"+quote(args.get("session_id") or client.authorized_session,safe=""))
        return result
    if name == "localpilot_events":
        events=[]
        for event in client.events(args["task_id"],after=args.get("after",0)):
            events.append(event)
            if len(events)>=args.get("limit",1):break
        return {"events":events,"cursor_instruction":"Use data.sequence or last snapshot last_event_id. EOF/disconnect never means completion."}
    if name == "localpilot_submit":
        args = dict(args); text = args.pop("input"); key = args.pop("idempotency_key")
        return client.submit(text, idempotency_key=key, **args)
    if name in {"localpilot_status","localpilot_result"}:
        return client.status(args["task_id"])
    if name == "localpilot_cancel":
        return client.cancel(args["task_id"])
    return client.continue_task(args["task_id"], args["action_id"])


def mcp(client, source=sys.stdin, target=sys.stdout):
    for line in source:
        message = None
        try:
            if len(line) > 1048576:
                raise ValueError("MCP request exceeds limit")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Expected JSON-RPC object")
            if "id" not in message:
                continue
            if message.get("jsonrpc")!="2.0":raise ValueError("JSON-RPC 2.0 required")
            method, params = message.get("method"), message.get("params", {})
            if not isinstance(params,dict):raise ValueError("Object params required")
            if method == "initialize":
                result = {"protocolVersion": params.get("protocolVersion") if params.get("protocolVersion") in {"2024-11-05","2025-03-26","2025-06-18","2025-11-25","2026-07-28"} else "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "localpilot-agent", "version": "5.0.0b20"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    value = invoke(client, params["name"], params.get("arguments", {}))
                    result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False}
                except HTTPError as exc:
                    # Do not return arbitrary upstream error bodies or credentials.
                    try:
                        body=json.loads(exc.read(8192));code=(body.get("error") or {}).get("code")
                    except (ValueError,OSError):code=None
                    finally:exc.close()
                    result = {"content": [{"type": "text", "text": json.dumps({"http_status": exc.code, "status": "service_rejected","code":code if isinstance(code,str) and len(code)<128 else None})}], "isError": True}
                except (OSError,TimeoutError):
                    result={"content":[{"type":"text","text":json.dumps({"status":"transport_unknown","instruction":"Query the same task or retry identical submit with original key; never infer completion or replay an effect."})}],"isError":True}
            else:
                target.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Method not found"}}) + "\n"); target.flush(); continue
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except Exception as exc:
            reply = {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                     "error": {"code": -32602, "message": "Adapter request failed: " + type(exc).__name__}}
        target.write(json.dumps(reply, ensure_ascii=False) + "\n"); target.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp", action="store_true")
    parser.add_argument("--connection",help="Owner-only integration connection file; no credentials in arguments")
    parser.add_argument("operation", choices=[t["name"] for t in TOOLS], nargs="?")
    parser.add_argument("--arguments", help="JSON arguments; token always comes from environment")
    args = parser.parse_args(argv)
    if args.connection:
        import stat,re
        def private(path):
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>1048576:raise ValueError('Unsafe private connection')
                return os.read(fd,1048577).decode()
            finally:os.close(fd)
        config=json.loads(private(args.connection))
        token=os.environ.get(config['token_env'])
        if not token:
            for line in private(config['credential_file']).splitlines():
                match=re.fullmatch(r'export ([A-Z][A-Z0-9_]*)=([a-zA-Z0-9_-]+)',line)
                if not match:raise ValueError('Unsupported credentials grammar')
                if match[1]==config['token_env']:token=match[2]
        if not token:raise ValueError('Configured client credential unavailable; run integrations doctor')
        client=Client(config['url'],token=token)
        client.authorized_session=config.get('session_id')
    else:
        client = Client(os.environ.get("LOCALPILOT_URL", "http://127.0.0.1:8765"), token=os.environ["LOCALPILOT_TOKEN"])
    if args.mcp:
        return mcp(client)
    if not args.operation or not args.arguments:
        parser.error("operation and --arguments are required")
    print(json.dumps(invoke(client, args.operation, json.loads(args.arguments)), ensure_ascii=False))


if __name__ == "__main__":
    main()

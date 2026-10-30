"""Create a new private deployment config and separate client token environment file."""
import argparse
import json
import os
from pathlib import Path
import secrets


def write_new(path, text):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w") as file:file.write(text)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",required=True)
    parser.add_argument("--directory",default="~/.local/share/localpilot-service")
    parser.add_argument("--model",required=True)
    parser.add_argument("--base-url",default="http://127.0.0.1:1234/v1")
    parser.add_argument("--deepseek-key-file")
    parser.add_argument("--api-key-env",default="")
    parser.add_argument("--managed-qwen35",action="store_true")
    parser.add_argument("--cloud-key-file")
    parser.add_argument('--omlx', action='store_true', help='Use existing oMLX service without owning or loading it')
    args=parser.parse_args(argv)
    workspace=Path(args.workspace).expanduser().resolve(strict=True)
    directory=Path(args.directory).expanduser().resolve()
    if not workspace.is_dir() or directory.is_relative_to(workspace):parser.error("Private service directory must be outside the task workspace")
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.stat().st_mode&0o077 or directory.stat().st_uid!=os.getuid():parser.error("Service directory must be owner-only")
    names=["codex","dsh","companion","http","operator"]
    clients=[{"subject":n,"token_env":"LOCALPILOT_"+n.upper()+"_TOKEN","routes":{"localpilot":"default"},
              **({"operator":True,"scopes":["read","control","cancel"],"approval_for":names[:-1]} if n=="operator" else {})} for n in names]
    backend={"kind":"deepseek","model":args.model,"key_file":str(Path(args.deepseek_key_file).expanduser().resolve())} if args.deepseek_key_file else {"kind":"local-openai","model":args.model,"base_url":args.base_url}
    if args.omlx:
        if args.deepseek_key_file or args.managed_qwen35: parser.error('oMLX shared service is a separate local provider')
        backend.update(kind='omlx', include_stream_usage=True, chat_template_kwargs={'enable_thinking':False})
    config={"schema_version":1,"host":"127.0.0.1","port":8765,"data_dir":str(directory/"data"),"clients":clients,
        "routes":{"default":{"workspace":str(workspace),"cache_stable_prefix":True,"backend":backend,"permissions":"approve-mutations",
            "capabilities":{"read":True,"write":True,"execute":False},"cloud_egress":"REQUIRES_APPROVAL" if args.deepseek_key_file else "LOCAL_ONLY"}}}
    if args.api_key_env:
        import re
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",args.api_key_env):parser.error("API credential must be an environment variable name, never its value")
        if args.deepseek_key_file:parser.error("Choose the existing provider file or the local environment reference")
        backend["api_key_env"]=args.api_key_env
    # Companion keeps minimal reasoning separate from confirmed standard Agent help.
    from copy import deepcopy
    execution = deepcopy(config["routes"]["default"])
    execution.update(prompt_profile="standard", tool_profile="full")
    reasoning = deepcopy(execution)
    reasoning.update(prompt_profile="minimal_0", tool_profile="compact", reasoning_only=True, capabilities={"read":False,"write":False,"execute":False})
    config["routes"]["companion-execution"] = execution
    config["routes"]["companion-reasoning"] = reasoning
    next(c for c in clients if c["subject"] == "companion")["routes"] = {
        "localpilot":"companion-execution", "companion-reasoning":"companion-reasoning"}
    next(c for c in clients if c["subject"] == "http")["routes"] = {"localpilot":"default", "companion-reasoning":"companion-reasoning"}
    if args.managed_qwen35:
        from .cached_omlx import MODEL, SNAPSHOT
        if args.deepseek_key_file or args.model != MODEL:parser.error("Managed mode requires the approved cached Qwen3.6-35B model and a local primary")
        if not SNAPSHOT.is_dir() or not (SNAPSHOT/"config.json").is_file():parser.error("Approved model cache is absent; initialization never downloads weights")
        profile={"snapshot":str(SNAPSHOT),"port":8048,"idle_seconds":60,"memory_bytes":26*1024**3,"min_available_bytes":28*1024**3}
        for route_name in ("companion-execution","companion-reasoning"):
            route=config["routes"][route_name]
            route["backend"]={**route["backend"],"base_url":"http://127.0.0.1:8048/v1","include_stream_usage":True}
            route["backend"].pop("api_key_env",None)
            route["managed_local_model"]=profile
        config["routes"]["default"]["deployment_status"]="not_deployed"
        owner={"subject":"local","token_env":"LOCALPILOT_LOCAL_TOKEN","routes":{"localpilot":"companion-execution","companion-reasoning":"companion-reasoning"}}
        clients.append(owner)
        next(c for c in clients if c["subject"]=="operator")["approval_for"].append("local")
        next(c for c in clients if c["subject"]=="companion")["routes"]={}
        next(c for c in clients if c["subject"]=="http")["routes"]={"localpilot":"default"}
    else:
        owner=next(c for c in clients if c["subject"]=="companion")
    if args.omlx:
        from agent.omlx import OMLXBackend
        observation=OMLXBackend(base_url=args.base_url,model=args.model,
            api_key=os.environ.get(args.api_key_env) if args.api_key_env else None).inspect_service()
        if args.model not in {m['id'] for m in observation['models']} and not (args.model=='not-selected' and not observation['models']):parser.error('Selected model was not discovered by oMLX')
        for index, model in enumerate(observation['models']):
            route=deepcopy(execution)
            route['backend']['model']=model['id']
            route['backend']['context_budget']=min(model.get('context_budget') or 32768,65536)
            if (model.get('size_bytes') or 0)<=1500000000:
                route.update(reasoning_only=True,prompt_profile='minimal_0',tool_profile='compact',capabilities={'read':False,'write':False,'execute':False})
            import re
            parameters=re.search(r'(\d+(?:\.\d+)?)B',model['id'])
            capacity=min(100,int(float(parameters[1])*2)) if parameters else 0
            memory_rank=min(100,int((model.get('size_bytes') or 50*1024**3)/1024**3*2))
            route['routing_rank']={'speed':100-memory_rank, 'quality':capacity, 'efficiency':100-memory_rank,'balanced':100 if model['id']==args.model else 0}
            public='omlx-'+str(index+1)
            config['routes'][public]=route
            for client in clients:
                if not client.get('operator'): client['routes'][public]=public
        preferred=next((m for m in observation['models'] if m['id']=='mlx-community--Qwen3.6-35B-A3B-4bit' and m.get('revision')=='38740b847e4cb78f352aba30aa41c76e08e6eb46'),None)
        if preferred:
            for key in ['default','companion-execution','companion-reasoning']:
                config['routes'][key]['backend'].update(model=preferred['id'],context_budget=65536,timeout=180)
            execution=deepcopy(config['routes']['companion-execution'])
        v5=deepcopy(execution);v5['engine']='v5'
        config['routes']['local-v5']=v5
        for client in clients:
            if not client.get('operator'):client['routes']['local-v5']='local-v5'
        # All CLI/GUI/Companion clients use the same authenticated API, with
        # separate ownership namespaces. No shared model process is started.
    if args.cloud_key_file:
        if args.deepseek_key_file:parser.error("Choose a cloud-only primary or an optional consultation backend")
        cloud_route=deepcopy(reasoning)
        cloud_route.update(backend={"kind":"deepseek","model":"deepseek-flash","key_file":str(Path(args.cloud_key_file).expanduser().resolve())},cloud_egress="REQUIRES_APPROVAL",thinking="none")
        cloud_route.pop("managed_local_model",None)
        config["routes"]["companion-cloud-reasoning"]=cloud_route
        owner["routes"]["companion-cloud-reasoning"]="companion-cloud-reasoning"
        if args.omlx:
            agent_cloud=deepcopy(execution)
            agent_cloud.update(engine='v5', backend={**cloud_route['backend'],'kind':'deepseek-native'},cloud_egress='REQUIRES_APPROVAL',thinking='none')
            config['routes']['deepseek-agent']=agent_cloud
            for client in clients:
                if not client.get('operator'):client['routes']['deepseek-agent']='deepseek-agent'
    if args.managed_qwen35 or args.cloud_key_file or args.omlx:
        clients.append({"subject":"resource","token_env":"LOCALPILOT_RESOURCE_TOKEN","operator":True,"scopes":["read","resource_control"],"approval_for":[c['subject'] for c in clients if not c.get('operator')] if args.omlx else [owner["subject"]],"routes":{}})
    # Refuse existing targets before generating any new credentials.
    if (directory/"service.json").exists() or (directory/"clients.env").exists():parser.error("Configuration already exists; choose a new directory")
    write_new(directory/"service.json",json.dumps(config,indent=2)+"\n")
    write_new(directory/"clients.env","".join("export "+c["token_env"]+"="+secrets.token_urlsafe(32)+"\n" for c in clients))
    print(json.dumps({"config":str(directory/"service.json"),"token_environment":str(directory/"clients.env"),"provider_credentials":"not_copied","next":"Load clients.env in your own trusted shell, then start python -m localpilot_service --config ..."}))


if __name__=="__main__":main()

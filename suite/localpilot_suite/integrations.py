"""Scoped Skill/MCP installer. Never overwrites another server or global config."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from localpilot_service.cli import save, environment, connection
from localpilot_service.security import private_json
from localpilot_service.sdk import Client

VERSION='5.0.0b20'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def skill_files(path):
    # Portable Python precompiles package data too. Generated caches are never
    # Skill authority and are already excluded by the copy/uninstall rules.
    return [p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
def skill_source():
    choices=[Path(__file__).resolve().parents[2]/'localpilot-agent',Path(__file__).resolve().parents[1]/'share/localpilot/skill',Path(sys.prefix)/'share/localpilot/skill']
    for path in choices:
        if (path/'SKILL.md').is_file():return path
    raise ValueError('Skill assets missing; install the matching Core wheel')

def principal(home,host):
    config=private_json(home/'service.json')
    match=next((p for p in config['clients'] if p['subject']==host and not p.get('operator')),None)
    if not match:raise ValueError('Configure a separate ordinary '+host+' client in service.json and restart Core; never reuse operator credentials')
    key=environment(home).get(match['token_env'])
    if not key:raise ValueError('Client token missing from private clients.env')
    c=connection(home);probe=Client(c.base_url,token=key);health=probe.request('/healthz')
    if health['client_subject']!=host:raise ValueError('Authenticated identity differs from target host')
    return probe,match

def install(home,host,root):
    home=home.resolve(strict=True)
    c,p=principal(home,host)
    root=root.resolve(strict=True)
    dest=root/'.agents/skills/localpilot-agent';assets=skill_source()
    config=root/('.codex/config.toml' if host=='codex' else '.localpilot/dsh.patch.json')
    record=root/'.localpilot'/('integration-'+host+'.json')
    if record.exists():raise ValueError('Integration already installed; run doctor or uninstall before reinstalling')
    cache_only=dest.exists() and all('__pycache__' in f.parts and f.suffix=='.pyc' for f in dest.rglob('*') if f.is_file())
    if dest.exists() and not cache_only and any(not (dest/f.relative_to(assets)).is_file() or sha(dest/f.relative_to(assets))!=sha(f) for f in skill_files(assets)):
        raise ValueError('Existing localpilot-agent Skill differs; preserve it and select another project')
    for target in (config,dest,record):
        if target.is_symlink() or not target.parent.resolve().is_relative_to(root):raise ValueError('Project installation paths must remain inside the selected project; symlinks cannot change global configuration')
    previous=config.read_text() if config.exists() else ''
    if host=='codex':
        import tomllib
        parsed=tomllib.loads(previous)
        if 'localpilot' in parsed.get('mcp_servers',{}):raise ValueError('Existing localpilot MCP server preserved; choose another project or reconcile it manually')
    elif config.exists():raise ValueError('Existing DSH overlay preserved')
    private=home/'integrations'/(host+'-'+hashlib.sha256(str(root).encode()).hexdigest()[:16]);private.mkdir(parents=True,exist_ok=True,mode=0o700)
    client_file=private/'client.env'
    fd=os.open(client_file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write('export '+p['token_env']+'='+c.token+'\n')
    credential=private/'connection.json';save(credential,{'url':c.base_url,'token_env':p['token_env'],'credential_file':str(client_file)})
    created_skill=not dest.exists() or cache_only
    if created_skill:
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(assets,dest,dirs_exist_ok=cache_only,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    adapter=dest/'scripts/localpilot_adapter.py'
    argv=['-B',str(adapter),'--connection',str(credential),'--mcp']
    if host=='codex':
        addition='\n[mcp_servers.localpilot]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+json.dumps(argv)+'\nstartup_timeout_sec = 20\ntool_timeout_sec = 45\n'
        config.parent.mkdir(parents=True,exist_ok=True);config.write_text(previous+addition)
    else:
        addition=json.dumps([{'insert':[{'id':'localpilot-agent-mcp','name':'@deepseek-ai/dsh-mcp-client','config':{'serverName':'localpilot','transport':'stdio','command':sys.executable,'args':argv,'failOnStartupError':True,'toolCallTimeoutMs':45000}}]}],indent=2)+'\n'
        config.parent.mkdir(parents=True,exist_ok=True);config.write_text(addition)
    record.parent.mkdir(parents=True,exist_ok=True)
    save(record,{'host':host,'version':VERSION,'config':str(config),'addition':addition,'config_sha256':sha(config),'credential':str(credential),'client_file':str(client_file),'created_skill':created_skill,'files':{str(f):sha(f) for f in dest.rglob('*') if f.is_file()}})
    return {'status':'installed','host':host,'skill':str(dest),'config':str(config),'client_subject':host,'activation':'Reload Codex in this trusted project' if host=='codex' else 'dsh headless --patch '+str(config)+' --json "Use LocalPilot ..."','permission':'Host tool approvals still apply; Skill grants no authority'}

def uninstall(host,root,home):
    root=root.resolve(strict=True);home=home.resolve(strict=True)
    record=root/'.localpilot'/('integration-'+host+'.json')
    if not record.exists():raise ValueError('No owned integration record here')
    value=private_json(record);config=Path(value['config'])
    expected=root/('.codex/config.toml' if host=='codex' else '.localpilot/dsh.patch.json')
    private=home/'integrations'/(host+'-'+hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16])
    if config!=expected or Path(value['credential'])!=private/'connection.json' or value.get('client_file',str(private/'client.env'))!=str(private/'client.env'):
        raise ValueError('Installer record paths differ from the selected project/service; nothing removed')
    skill=root/'.agents/skills/localpilot-agent'
    if any(Path(f).is_symlink() or not Path(f).resolve().is_relative_to(skill.resolve()) for f in value['files']):raise ValueError('Installer record contains a file outside its Skill')
    if sha(config)!=value['config_sha256']:raise ValueError('Configuration changed since install; preserve it and remove the LocalPilot table manually')
    if any(not Path(p).is_file() or sha(p)!=h for p,h in value['files'].items()):raise ValueError('Skill was edited; preserve it and reconcile manually')
    text=config.read_text();addition=value['addition']
    if host=='codex':config.write_text(text[:-len(addition)])
    else:config.unlink()
    other=root/'.localpilot'/('integration-'+('dsh' if host=='codex' else 'codex')+'.json')
    if value['created_skill'] and other.exists():
        remaining=private_json(other);remaining['created_skill']=True;save(other,remaining)
    if value['created_skill'] and not other.exists():
        for p in value['files']:Path(p).unlink()
        # Only empty owned directories; generated caches or user files are preserved.
        for d in sorted((root/'.agents/skills/localpilot-agent').rglob('*'),key=lambda p:len(p.parts),reverse=True):
            if d.is_dir():
                try:d.rmdir()
                except OSError:pass
        try:(root/'.agents/skills/localpilot-agent').rmdir()
        except OSError:pass
    Path(value['credential']).unlink(missing_ok=True)
    (private/'client.env').unlink(missing_ok=True);record.unlink()
    return {'status':'uninstalled','host':host}

def doctor(home,root):
    rows=[]
    for host in ['codex','dsh']:
        row={'host':host,'installed':False,'connected':False}
        path=root/'.localpilot'/('integration-'+host+'.json')
        try:
            if not path.exists():raise ValueError('Run integrations install '+host+' --project PATH')
            installed=private_json(path);row.update(installed=True,skill_version=installed['version'])
            c,p=principal(home,host);health=c.request('/healthz');models=c.request('/localpilot/v1/model-registry')
            row.update(auth_valid=True,client_subject=health['client_subject'],scopes=p.get('scopes',['submit','read','cancel']),api_version=health['compatibility']['agent_service_api'],capabilities=models)
            adapter=root/'.agents/skills/localpilot-agent/scripts/localpilot_adapter.py'
            result=subprocess.run([sys.executable,'-B',str(adapter),'--connection',installed['credential'],'--mcp'],input=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'})+'\n',capture_output=True,text=True,timeout=10)
            listing=json.loads(result.stdout)
            if result.returncode or 'result' not in listing:raise ValueError('MCP schema/launch failure; check installed Core and adapter paths')
            connection_info=private_json(installed['credential'])
            if connection_info.get('session_id'):row['authorized_session']=c.request('/localpilot/v1/sessions/'+connection_info['session_id'])
            row.update(connected=True,mcp_adapter='ready',tools=[t['name'] for t in listing['result']['tools']],host_approval='Independent; connection health does not prove model invocation',recent_error=None)
        except Exception as exc:row['recent_error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__;row['next_step']='Check Core status, dedicated client token, project trust and host MCP approval; rerun doctor'
        rows.append(row)
    return {'version':VERSION,'integrations':rows}

def authorize(home,host,root,folder,access,mode,model,cloud_paths):
    import uuid
    c,p=principal(home,host)
    env=environment(home);key=env.get('LOCALPILOT_OPERATOR_TOKEN')
    if not key:raise ValueError('Separate human operator credential required; ordinary host credentials cannot authorize scopes')
    op=Client(c.base_url,token=key)
    grant=op.request('/localpilot/v1/workspace-grants',{'client_subject':host,'operation':'grant','folder':str(Path(folder).expanduser().resolve(strict=True)),'scope':access,'cloud_paths':cloud_paths})
    session=op.request('/localpilot/v1/desktop-sessions',{'client_subject':host,'model':model,'source':'balanced','options':{'permission_mode':mode,'agent_profile':'standard','workspace_grant':grant['id']}},key='integration-authorization-'+uuid.uuid4().hex)
    record=root/'.localpilot'/('integration-'+host+'.json')
    if record.exists():
        installed=private_json(record);path=Path(installed['credential']);connection=private_json(path);connection['session_id']=session['id'];save(path,connection)
    return {'status':'authorized','client_subject':host,'session_id':session['id'],'grant_id':grant['id'],'scope':access,'workspace':grant['path'],'cloud_paths':cloud_paths,'authority':'Skill/MCP ordinary identity still cannot approve high risk operations'}

def main(argv,home):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['install','uninstall','doctor','authorize']);p.add_argument('host',nargs='?',choices=['codex','dsh']);p.add_argument('--project',default=os.getcwd());p.add_argument('--scope',choices=['project','user'],default='project');p.add_argument('--confirm-user',action='store_true')
    p.add_argument('--folder');p.add_argument('--access',choices=['read','organize','modify'],default='read');p.add_argument('--permission-mode',choices=['isolated','request','workspace','ask','safe','uncertain','full'],default='safe');p.add_argument('--model',default='localpilot');p.add_argument('--cloud-paths-json',default='[]');p.add_argument('--confirmed',action='store_true')
    a=p.parse_args(argv)
    if a.scope=='user' and not a.confirm_user:raise ValueError('User-level changes require explicit --scope user --confirm-user; project install is the default')
    root=Path.home() if a.scope=='user' else Path(a.project).expanduser().resolve(strict=True)
    if root==Path.home() and a.scope!='user':raise ValueError('Home is a user-level target; use --scope user --confirm-user explicitly')
    if a.action=='doctor':return doctor(home,root)
    if a.action=='authorize':
        if not a.host or not a.folder or not a.confirmed:raise ValueError('An explicit host, --folder and --confirmed are required; installation alone never grants a directory')
        return authorize(home,a.host,root,a.folder,a.access,a.permission_mode,a.model,json.loads(a.cloud_paths_json))
    if not a.host:raise ValueError('Choose codex or dsh')
    return install(home,a.host,root) if a.action=='install' else uninstall(a.host,root,home)

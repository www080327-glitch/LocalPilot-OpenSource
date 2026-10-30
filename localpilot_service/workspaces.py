"""Explicit operator folder grants bound to subject, executor and directory identity."""
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import uuid
from localpilot_api.service import APIError
from .security import private_json

class WorkspaceGrants:
    def __init__(self, path, private_roots=()):
        self.path=Path(path); self.lock=threading.RLock(); self.private_roots=[Path(p).resolve() for p in private_roots]
        self.grants=private_json(self.path) if self.path.exists() else {}

    def save(self):
        tmp=self.path.with_name(self.path.name+'.tmp-'+uuid.uuid4().hex)
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(self.grants,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,self.path)

    def create(self,subject,folder,scope,cloud_paths):
        if scope not in {'read','organize','modify'} or not isinstance(folder,str) or not Path(folder).is_absolute():
            raise APIError('Select an absolute folder and read/organize/modify scope')
        from agent.safe_files import entry
        from agent.safety import sensitive_path
        root=Path(folder).resolve(strict=True)
        if root in {Path('/'),Path.home()} or sensitive_path(root) or any(p==root or p.is_relative_to(root) or root.is_relative_to(p) for p in self.private_roots):
            raise APIError('Folder overlaps private service data or unrestricted Home/disk','workspace_forbidden',403)
        if not isinstance(cloud_paths,list) or len(cloud_paths)>256 or any(not isinstance(p,str) or not p or Path(p).is_absolute() or '..' in Path(p).parts or str(Path(p))!=p or sensitive_path(p) for p in cloud_paths):
            raise APIError('Cloud disclosure requires at most 256 exact relative paths')
        try:
            fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try: info=os.fstat(fd);os.listdir(fd) # Actual executor probe; picker alone is not proof.
            finally: os.close(fd)
        except PermissionError:
            raise APIError('Executor cannot read this folder. macOS: System Settings > Privacy & Security > Files and Folders; authorize the displayed LocalPilot executor, then select again. No TCC bypass attempted.','system_authorization_required',403)
        grant={'id':'grant_'+uuid.uuid4().hex,'subject':subject,'path':str(root),'scope':scope,
               'device':info.st_dev,'inode':info.st_ino,'executor_uid':os.getuid(),
               'executor':str(Path(__import__('sys').executable).resolve()),'revoked':False,'cloud_paths':cloud_paths}
        with self.lock:
            self.grants[grant['id']]=grant;self.save()
        return dict(grant)

    def get(self,gid,subject=None):
        with self.lock:
            grant=self.grants.get(gid)
            if not grant or (subject is not None and grant['subject']!=subject):
                raise APIError('Folder grant not found','workspace_forbidden',403)
            return dict(grant)

    def validate(self,gid):
        grant=self.get(gid)
        if grant['revoked'] or grant['executor_uid']!=os.getuid() or grant['executor']!=str(Path(__import__('sys').executable).resolve()):
            raise PermissionError('Folder grant revoked or execution identity changed; select again')
        fd=os.open(grant['path'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: info=os.fstat(fd)
        finally: os.close(fd)
        if (info.st_dev,info.st_ino)!=(grant['device'],grant['inode']):
            raise PermissionError('Granted folder identity changed; select again')
        return grant

    @contextmanager
    def guard(self,gid,name,args):
        with self.lock:
            grant=self.validate(gid)
            if name in {'execute','run_command','shell'} or grant['scope']=='read' and name not in {'read_file','list_directory','list_entries','file_info','search_text','inspect_file'} or grant['scope']=='organize' and name not in {'read_file','list_directory','list_entries','file_info','search_text','inspect_file','make_directory','move_file','copy_file'}:
                raise PermissionError('Tool outside selected folder scope')
            yield

    def revoke(self,gid,subject):
        with self.lock:
            self.get(gid,subject); self.grants[gid]['revoked']=True;self.save()
        return {'id':gid,'revoked':True}

    def bind(self,runtime,gid):
        if runtime.computer:
            raise APIError('Computer Use scopes require a separate host route; folder rebinding is not qualified','computer_scope_rebind_not_qualified',409)
        from agent.registry import create_default_registry
        from agent.safety import CapabilityPolicy
        from agent.hybrid import CloudEgressPolicy
        grant=self.get(gid) # Revoked sessions restore for reconciliation; dispatch always validates.
        if getattr(runtime, '_plugin_options', None):
            from localpilot_plugins.adapter import private_roots
            if any(Path(private).is_relative_to(Path(grant['path']).resolve()) for private in private_roots(runtime)):
                raise APIError('Selected workspace overlaps protected native plugin or Skill storage')
        old=runtime.registry
        caps=old.gateway.capabilities
        registry=create_default_registry(grant['path'],permission_mode=old.gateway.mode,
            capabilities=CapabilityPolicy(read=caps.read,write=caps.write and grant['scope']!='read',execute=False,read_only=caps.read_only or grant['scope']=='read'),
            data_policy=old.gateway.data_policy,tool_profile=old.tool_profile,file_operations=True)
        registry.authorization_guard=lambda name,args:self.guard(gid,name,args)
        registry.read_cache=runtime.working.cache
        registry.record_read_absence=runtime.engine_policy is not None
        runtime.registry=registry;runtime.workspace=registry.workspace_root
        if getattr(runtime, '_plugin_options', None):
            manager = getattr(old, 'plugin_manager', None)
            if manager:
                manager.close()
            from localpilot_plugins.adapter import configure_session
            configure_session(runtime, **runtime._plugin_options)
        # Folder authority does not grant cloud disclosure. Exact selected paths only.
        if runtime.hybrid:
            egress=runtime.hybrid.policy.egress
            runtime.hybrid.policy=replace(runtime.hybrid.policy,egress=CloudEgressPolicy(egress.mode,tuple(grant['cloud_paths']),egress.max_request_bytes))
        # A fixture verifier cannot attest a newly selected folder.
        if old.workspace_root!=registry.workspace_root:
            runtime.verification_callback=None
            runtime.completion_check=None
            for backend in ([runtime.current_backend]+list(runtime.hybrid.catalog.values()) if runtime.hybrid else [runtime.current_backend]):
                if hasattr(backend,"service_contract"):backend.service_contract.pop("host_verification",None)
        runtime._refresh_prompt()


def handle(server,principal,body=None):
    if not principal.operator or 'control' not in principal.scopes:
        raise APIError('Folder selection requires trusted human operator','control_required',403)
    if not isinstance(body,dict) or body.get('client_subject') not in principal.approval_for:
        raise APIError('Explicit client identity required','scope_forbidden',403)
    subject=body['client_subject'];store=server.workspace_grants
    if set(body)=={'client_subject','operation'} and body['operation']=='list':
        rows=[]
        for g in list(store.grants.values()):
            if g['subject']!=subject:continue
            row=dict(g)
            try:store.validate(g['id']);row.update(usable=True,invalid_reason=None)
            except (OSError,APIError):row.update(usable=False,invalid_reason='revoked' if g['revoked'] else 'authorization_changed_select_again')
            rows.append(row)
        return {'grants':rows}
    if set(body)=={'client_subject','operation','grant_id'} and body['operation']=='revoke':
        return store.revoke(body['grant_id'],subject)
    if set(body)=={'client_subject','operation','folder','scope','cloud_paths'} and body['operation']=='grant':
        return store.create(subject,body['folder'],body['scope'],body['cloud_paths'])
    raise APIError('Exact folder authorization required')

def verify_operations(tools,root):
    """Fresh physical effects only, not semantic task/engineering acceptance."""
    from agent.safe_files import inspect_file
    expected={};count=0
    for tool in tools:
        if tool.get('name') not in {'make_directory','move_file','copy_file'}:continue
        count+=1;result=(tool.get('payload') or {}).get('result') or {}
        if result.get('scope_receipt'):
            return {'status':'NOT_RUN','scope':'One-operation receipt contains inline physical verification; fresh outside reads require new approval','receipts':count,'inline_verification':result.get('verification','UNKNOWN')}
        if result.get('action_may_have_applied') or result.get('status') in {'unknown','UNKNOWN'}:
            return {'status':'UNKNOWN','scope':'filesystem effects only','receipts':count,'replay_allowed':False}
        if result.get('status')!='ok':return {'status':'FAIL','scope':'filesystem effects only','receipts':count}
        if result.get('operation')=='move':expected[result['source']]=None
        expected[result['destination']]=result['after']
    if not count:return {'status':'NOT_RUN','scope':'filesystem effects only','receipts':0}
    for path,want in expected.items():
        try:actual=inspect_file(root,path)
        except FileNotFoundError:actual=None
        except (ValueError,OSError):return {'status':'UNKNOWN','scope':'filesystem effects only','receipts':count}
        if want is None:
            if actual is not None:return {'status':'FAIL','scope':'filesystem effects only','receipts':count}
        elif actual is None or any(actual.get(k)!=want.get(k) for k in ('device','inode','type')) or want.get('sha256') and actual.get('sha256')!=want['sha256']:
            return {'status':'FAIL','scope':'filesystem effects only','receipts':count}
    return {'status':'PASS','scope':'current paths, identities and content match receipts; semantic requirements remain independently verified','receipts':count}

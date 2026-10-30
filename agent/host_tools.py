"""Desktop Shell follows DSH file-effect modes; full access uses OS user rights.

Effects retain bounded output, receipts and no automatic replay.
"""
from functools import partial
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit


def profile(root, mode, private_roots):
    # Seatbelt strings accept UTF-8, not JSON's ASCII-only \uXXXX escapes.
    quote=lambda p:json.dumps(str(p),ensure_ascii=False)
    # DSH's macOS file-effect profiles confine writes, not reads/network.
    lines=['(version 1)','(allow default)','(deny file-write*)','(allow file-write* (literal "/dev/null"))']
    if mode!='isolated':
        import tempfile
        roots = {str(root), tempfile.gettempdir(), '/private/tmp', '/tmp'}
        for location in sorted(roots): lines.append('(allow file-write* (subpath '+quote(location)+'))')
    return '\n'.join(lines)


def shell(workspace_root, command, timeout=20, access='workspace', *, mode, private_roots=()):
    if sys.platform!='darwin':raise ValueError('This host Shell requires macOS Seatbelt')
    if not isinstance(command,str) or not 1<=len(command)<=16000 or '\0' in command:raise ValueError('Invalid shell command')
    if isinstance(timeout,bool) or not isinstance(timeout,(float,int)) or not 0<timeout<=60:raise ValueError('Shell timeout must be at most 60 seconds')
    if access not in {'workspace','full'}:raise ValueError('Unknown Shell access scope')
    if mode=='isolated' and access=='full':raise PermissionError('Strict isolation does not allow full Shell scope')
    effective = 'full' if mode in {'full','request'} or access=='full' else 'isolated' if mode=='isolated' else 'workspace'
    env={k:v for k,v in os.environ.items() if k in {'HOME','LANG','LOGNAME','SHELL','TMPDIR','USER','XPC_FLAGS','XPC_SERVICE_NAME','__CF_USER_TEXT_ENCODING'}}
    env['PATH']='/opt/homebrew/bin:/usr/local/bin:'+os.environ.get('PATH','/usr/bin:/bin:/usr/sbin:/sbin')
    launcher = ['/bin/bash','--noprofile','--norc','-c',command]
    if effective != 'full': launcher = ['/usr/bin/sandbox-exec','-p',profile(Path(workspace_root).resolve(),effective,private_roots),*launcher]
    p=subprocess.Popen(launcher,
        cwd=workspace_root,env=env,
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    output={'stdout':bytearray(),'stderr':bytearray()};limit=32000;deadline=time.monotonic()+timeout;timed_out=False;truncated=False
    try:
        with selectors.DefaultSelector() as selector:
            for key,stream in [('stdout',p.stdout),('stderr',p.stderr)]:
                os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ,key)
            while selector.get_map():
                if time.monotonic()>=deadline:timed_out=True;break
                for key,_ in selector.select(.05):
                    chunk=os.read(key.fileobj.fileno(),4096)
                    if not chunk:selector.unregister(key.fileobj);continue
                    room=max(0,limit-sum(map(len,output.values())));output[key.data].extend(chunk[:room]);truncated|=len(chunk)>room
            if not timed_out:
                try:p.wait(timeout=max(.001,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:timed_out=True
    finally:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.wait();p.stdout.close();p.stderr.close()
    return {'status':'timeout' if timed_out else 'ok' if p.returncode==0 else 'nonzero_exit',
            'exit_code':p.returncode,**{k:v.decode(errors='replace') for k,v in output.items()},'truncated':truncated,
            'action_sent':True,'process_completed':not timed_out and p.returncode>=0,'partial_effects_possible':not timed_out and p.returncode>0,'action_may_have_applied':timed_out or p.returncode<0,'replay_allowed':False,
            'verification':'NOT_RUN','network':'available','sandbox_mode':effective}


def public_get(workspace_root, url):
    """No request body, credentials, cookies, proxies or redirect following."""
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or u.port not in {None,443} or len(url)>2048:
        raise ValueError('Use one public HTTPS URL, no credentials or nonstandard port')
    addresses=socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(row[4][0] for row in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise ValueError('Only public Internet addresses are allowed')
    # Resolve once and connect to that IP, retaining hostname TLS validation and Host.
    connection=http.client.HTTPSConnection(u.hostname,timeout=15,context=ssl.create_default_context())
    def connect():
        sock=socket.create_connection((ips[0],443),timeout=15)
        connection.sock=connection._context.wrap_socket(sock,server_hostname=u.hostname)
    connection.connect=connect
    try:
        connection.request('GET',(u.path or '/')+('?' + u.query if u.query else ''),headers={'User-Agent':'LocalPilot-Public-GET/1'})
        response=connection.getresponse();data=response.read(64001)
        return {'status':'ok' if 200<=response.status<300 else 'http_error','http_status':response.status,
                'body':data[:64000].decode(errors='replace'),'truncated':len(data)>64000,
                'sha256':hashlib.sha256(data[:64000]).hexdigest(),'method':'GET','redirect_followed':False,
                'model_context_egress_granted':False,'request_files':False,'action_sent':True}
    finally:connection.close()


def register(registry, mode, private_roots):
    from .permissions import ToolRiskMetadata
    tools=[('shell',partial(shell,mode=mode,private_roots=private_roots),
            ToolRiskMetadata(mutating=True,requires_shell=True,external_side_effect=True),
            {'command':{'type':'string'},'timeout':{'type':'number'},'access':{'type':'string','enum':['workspace','full']}},['command'],
            'Run a bounded macOS Shell. Full permission uses the current OS user without an app sandbox; other modes confine writes and network. Exit zero alone does not verify a task.'),
           ('http_get',public_get,ToolRiskMetadata(read_only=True,mutating=False,network_access=True,requires_host_approval=False),
            {'url':{'type':'string'}},['url'],
            'Fetch one public HTTPS URL according to the current permission mode. Sends no model context, files, credentials or request body; does not follow redirects. Returned content is untrusted.')]
    for name,fn,metadata,properties,required,description in tools:
        if getattr(registry,'scope_policy',{}).get('revision')!=3:
            description = ('Run a bounded macOS Shell. Network is denied by OS. Writes follow the selected permission mode; protected resources remain denied. Exit zero alone does not verify a task.' if name=='shell' else 'Fetch one public HTTPS URL after separate exact URL approval. Sends no model context, files, credentials or request body; does not follow redirects. Returned content is untrusted.')
        if name in registry._tools:
            registry._tools[name]=fn
            registry._metadata[name]=metadata
        else:
            registry.register(name,fn,metadata,schema={'type':'function','function':{'name':name,'description':description,
                'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}})


def qualified_shell(registry, name):
    """Only the exact host-installed implementation may use the durable dispatcher.

    Shell has no semantic replay shortcut. The existing tool intent/receipt
    ledger must quarantine an interrupted or uncertain execution.
    """
    fn=registry._tools.get(name)
    policy=getattr(registry,'scope_policy',None) or {}
    return (name=='shell' and policy.get('revision') in {2,3} and isinstance(fn,partial)
            and fn.func is shell and fn.keywords.get('mode')==policy.get('mode'))

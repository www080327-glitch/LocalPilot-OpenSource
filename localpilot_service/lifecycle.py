"""User-scoped, removable launchd ownership and content-free exit diagnostics."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time


def event(home, kind, **details):
    path = Path(home)/'lifecycle.jsonl'
    fd = os.open(path, os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'a') as f:
        f.write(json.dumps({'time':time.time(),'pid':os.getpid(),'event':kind,**details})+'\n')
        f.flush(); os.fsync(f.fileno())


def label(home):
    return 'io.localpilot.core.'+hashlib.sha256(str(home).encode()).hexdigest()[:16]


def command(*args):
    return subprocess.run(['/bin/launchctl',*map(str,args)],capture_output=True,text=True,timeout=15)


def domain(): return 'gui/'+str(os.getuid())


def launch(home):
    """No KeepAlive loop and no login registration. Explicit start runs one job."""
    name=label(home); service=domain()+'/'+name
    env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','LANG','LC_ALL','PYTHONHOME','SSL_CERT_FILE'}}
    roots=[str(Path(__file__).resolve().parent.parent)]+os.environ.get('PYTHONPATH','').split(os.pathsep)
    env.update(PYTHONPATH=os.pathsep.join(dict.fromkeys(p for p in roots if p)),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
    spec={'Label':name,'ProgramArguments':[sys.executable,'-m','localpilot_service.cli','--home',str(home),'_serve'],
          'EnvironmentVariables':env,'WorkingDirectory':str(home),'RunAtLoad':True,'KeepAlive':False,
          'ProcessType':'Interactive','ExitTimeOut':30,'StandardOutPath':str(home/'service.log'),
          'StandardErrorPath':str(home/'service.log'),'Umask':0o077}
    path=home/'core-launch-agent.plist'
    existing=command('print',service)
    if existing.returncode==0:
        # A stopped registration can still point at an old APP/Python after upgrade.
        previous=plistlib.loads(path.read_bytes()) if path.is_file() and not path.is_symlink() else {}
        same=(previous.get('ProcessType')==spec['ProcessType'] and previous.get('ProgramArguments')==spec['ProgramArguments'] and all(
            previous.get('EnvironmentVariables',{}).get(k)==env.get(k) for k in ['PYTHONHOME','PYTHONPATH']))
        if same:
            result=command('kickstart',service)
            if result.returncode:raise ValueError('launchd start failed: '+result.stderr.strip()[:500])
            event(home,'launchd_start',label=name,keep_alive=False,login_autostart=False)
            return
        import re
        if re.search(r'^\s*pid = \d+',existing.stdout,re.M):
            raise ValueError('Existing launchd process is still active; explicitly stop it before changing runtime')
        result=command('bootout',service)
        if result.returncode:raise ValueError('Could not unregister the stopped previous Core runtime')
        event(home,'launchd_runtime_rebound',previous_executable=(previous.get('ProgramArguments') or [None])[0],executable=sys.executable)
    # Atomic private plist, never contains bearer tokens or provider keys.
    tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:plistlib.dump(spec,f)
    os.replace(tmp,path)
    result=command('bootstrap',domain(),path)
    if result.returncode:raise ValueError('launchd start failed: '+result.stderr.strip()[:500])
    event(home,'launchd_start',label=name,keep_alive=False,login_autostart=False)


def unregister(home):
    result=command('bootout',domain()+'/'+label(home))
    event(home,'launchd_unregister',returncode=result.returncode)
    return {'status':'unregistered' if result.returncode==0 else 'not_registered','login_autostart':False}


def diagnostic(home):
    result={'manager':'launchd' if sys.platform=='darwin' else 'detached','auto_restart':False}
    if sys.platform=='darwin':
        probe=command('print',domain()+'/'+label(home))
        result['registered']=probe.returncode==0
        result['launchd']=[line.strip() for line in probe.stdout.splitlines() if any(key in line for key in ['state =','pid =','last exit code =','last terminating signal =','runs ='])]
    path=home/'lifecycle.jsonl'
    result['events']=[json.loads(line) for line in path.read_text().splitlines()[-20:]] if path.exists() else []
    return result

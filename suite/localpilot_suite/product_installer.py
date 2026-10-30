"""Pinned official oMLX DMG installer. Never replaces an existing installation."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from urllib.request import urlopen

ASSETS={
 'sequoia':('oMLX-0.7.2-macos15-sequoia.dmg',837764819,'86e50d13ecbdf8531a5e39684619b0b0a609ec06e1c1fab866daa74e0e47b32e'),
 'tahoe':('oMLX-0.7.2-macos26-27.dmg',875184568,'0ceddaf7a8901d440bc88acb3e033b294ad4d1b45b57d02fb73833c839d270b9')}

def install():
    if platform.system()!='Darwin' or platform.machine()!='arm64':raise ValueError('Apple Silicon macOS required')
    existing=next((p/'oMLX.app' for p in [Path('/Applications'),Path.home()/'Applications'] if (p/'oMLX.app').exists()),None)
    if existing:return {'status':'existing','app':str(existing),'replaced':False}
    major=int(platform.mac_ver()[0].split('.')[0])
    if major<15:raise ValueError('macOS 15 or later is required')
    name,size,sha=ASSETS['tahoe' if major>=26 else 'sequoia']
    if shutil.disk_usage(Path.home()).free<4*size:raise ValueError('Insufficient space for verified installer')
    downloads=Path.home()/'Library/Caches/LocalPilot Installers';downloads.mkdir(parents=True,exist_ok=True)
    import uuid,fcntl,os
    from .installer_download import fetch
    dmg=downloads/name
    fd=os.open(downloads/'download.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('已有安装下载正在进行，请等待完成') from None
        fetch('https://github.com/jundot/omlx/releases/download/v0.7.2/'+name,dmg,size,sha)
    mount=Path(tempfile.mkdtemp(prefix='localpilot-omlx-'))
    try:
        subprocess.run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-mountpoint',str(mount),str(dmg)],capture_output=True,check=True,timeout=90)
        app=mount/'oMLX.app'
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],capture_output=True,check=True,timeout=60)
        destination=Path.home()/'Applications/oMLX.app';destination.parent.mkdir(exist_ok=True)
        if destination.exists():raise ValueError('An installation appeared; no files replaced')
        stage=destination.parent/('.localpilot-omlx-'+uuid.uuid4().hex);stage.mkdir()
        staged=stage/'oMLX.app'
        subprocess.run(['/usr/bin/ditto','--norsrc','--noextattr',str(app),str(staged)],check=True,timeout=120)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(staged)],capture_output=True,check=True,timeout=60)
        if destination.exists():raise ValueError('An installation appeared; staged evidence preserved')
        staged.rename(destination)
        return {'status':'installed','version':'0.7.2','sha256':sha,'app':str(destination),'next':'oMLX is installed. LocalPilot will prepare the local service after your confirmation.','replaced':False}
    finally:
        subprocess.run(['/usr/bin/hdiutil','detach',str(mount)],capture_output=True,timeout=30)


def initialize_service():
    """First installation only; no overwrite or takeover of an existing service."""
    import os
    import secrets
    import socket
    import time
    from localpilot_service.cli import save
    from localpilot_service.security import private_json
    from .desktop_setup import discover_omlx
    root=Path.home()/'.omlx';settings_file=root/'settings.json'
    if settings_file.exists():
        settings=private_json(settings_file)
        port=settings.get('server',{}).get('port')
        if type(port) is not int:raise ValueError('Existing oMLX settings require repair; preserved unchanged')
        try:
            discover_omlx(f'http://127.0.0.1:{port}/v1',settings.get('auth',{}).get('api_key'))
            return {'status':'existing','settings_preserved':True,'models_loaded':False}
        except Exception:
            if (root/'localpilot-owned-service.json').exists():return owned_service('recover')
            raise ValueError('已有 oMLX 尚未启动。请点“打开 oMLX”并完成系统确认，再重新检测') from None
    app=next((p/'oMLX.app' for p in [Path('/Applications'),Path.home()/'Applications'] if (p/'oMLX.app/Contents/MacOS/omlx-cli').is_file()),None)
    if not app:raise ValueError('Install the official oMLX application first')
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True,timeout=30)
    root.mkdir(exist_ok=True,mode=0o700)
    if root.is_symlink():raise ValueError('Refusing symbolic oMLX data directory')
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    model_dir=Path.home()/'Library/Application Support/LocalPilot Models';model_dir.mkdir(parents=True,exist_ok=True)
    settings={'server':{'host':'127.0.0.1','port':port,'cors_origins':[]},'model':{'model_dirs':[str(model_dir)],'model_fallback':False},
        'auth':{'api_key':secrets.token_urlsafe(32),'skip_api_key_verification':False},
        'cache':{'enabled':True,'ssd_cache_max_size':'8GB'},'scheduler':{'max_concurrent_requests':2}}
    # Exclusive create prevents races with oMLX's first-run window.
    fd=os.open(settings_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(settings,f);f.flush();os.fsync(f.fileno())
    env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','LANG','TMPDIR','SSL_CERT_FILE'}}
    with (root/'localpilot-installer.log').open('ab') as log:
        process=subprocess.Popen([str(app/'Contents/MacOS/omlx-cli'),'serve','--base-path',str(root)],cwd=str(root),env=env,stdout=log,stderr=log,start_new_session=True)
    import psutil
    save(root/'localpilot-owned-service.json',{'pid':process.pid,'created':psutil.Process(process.pid).create_time(),'app':str(app),'port':port})
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        if process.poll() is not None:raise ValueError('oMLX startup failed; original installer log retained')
        try:
            discover_omlx(f'http://127.0.0.1:{port}/v1',settings['auth']['api_key'])
            return {'status':'ready','port':port,'settings_created':True,'models_loaded':False,'model_dir':str(model_dir)}
        except Exception:time.sleep(.5)
    raise ValueError('oMLX startup state is UNKNOWN; inspect before retrying. Installer evidence retained.')


def owned_process_matches(process,record,app):
    """oMLX can change argv with setproctitle; birth/uid/bundle executable remain stable."""
    import os
    return (process.uids().real==os.getuid() and abs(process.create_time()-record['created'])<=.02
        and Path(process.exe()).resolve().is_relative_to(Path(app).resolve()/'Contents'))


def owned_service(action):
    """Control only an installer-owned oMLX with a verified process identity."""
    import os,time,psutil
    from localpilot_service.security import private_json
    from localpilot_service.cli import save
    from .desktop_setup import discover_omlx
    root=Path.home()/'.omlx'
    if not (root/'settings.json').exists():return {'status':'not_configured'}
    settings=private_json(root/'settings.json');port=settings.get('server',{}).get('port')
    if type(port) is not int or not 1<=port<=65535:raise ValueError('oMLX 配置需要修复，已保留')
    def ready():
        try:discover_omlx(f'http://127.0.0.1:{port}/v1',settings.get('auth',{}).get('api_key'));return True
        except Exception:return False
    healthy=ready();receipt=root/'localpilot-owned-service.json'
    if action=='status':return {'status':'ready' if healthy else 'unavailable','owned':receipt.exists()}
    if action in {'start','recover'} and healthy:return {'status':'ready','recovered':False}
    if not receipt.exists():raise ValueError('此 oMLX 由用户独立管理，请打开 oMLX；未接管其进程')
    record=private_json(receipt);app=Path(record['app'])
    if app not in [Path('/Applications/oMLX.app'),Path.home()/'Applications/oMLX.app']:
        raise ValueError('oMLX 安装身份不匹配，未启动或停止')
    try:
        process=psutil.Process(record['pid'])
        if not owned_process_matches(process,record,app):
            raise ValueError('oMLX 进程身份变化，未操作')
        if action=='stop':
            if not healthy:raise ValueError('oMLX 状态未知，未停止')
            from .product_control import OmlxAdmin
            admin=OmlxAdmin()
            if admin.request('/api/status').get('active_requests')!=0:raise ValueError('请先等待模型任务结束')
            process.terminate()
            try:process.wait(timeout=15)
            except psutil.TimeoutExpired:raise ValueError('oMLX 仍在停止，请重新检查；未强制终止') from None
            return {'status':'stopped'}
        raise ValueError('oMLX 进程仍存在但未就绪，请检查诊断；未重复启动')
    except psutil.NoSuchProcess:
        if action=='stop':return {'status':'stopped'}
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True,timeout=30)
    env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','LANG','TMPDIR','SSL_CERT_FILE'}}
    with (root/'localpilot-installer.log').open('ab') as log:
        child=subprocess.Popen([str(app/'Contents/MacOS/omlx-cli'),'serve','--base-path',str(root)],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
    save(receipt,{**record,'pid':child.pid,'created':psutil.Process(child.pid).create_time()})
    for _ in range(90):
        if ready():return {'status':'ready','recovered':True,'models_loaded':False}
        if child.poll() is not None:raise ValueError('oMLX 启动失败，日志已保留。可重试恢复服务')
        time.sleep(1)
    raise ValueError('oMLX 启动结果 UNKNOWN，请重新检测；未重复启动')

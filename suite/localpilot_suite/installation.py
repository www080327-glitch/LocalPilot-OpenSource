"""Bounded installation controls. No Agent loop, inference, or task replay."""
import contextlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import re


def pending_core(home):
    import psutil
    wanted=Path(home).resolve()
    for process in psutil.process_iter(['uids','cmdline']):
        try:
            cmd=process.info['cmdline'] or []
            if (process.info['uids'].real==os.getuid() and len(cmd)==6 and
                cmd[1:4]==['-m','localpilot_service.cli','--home'] and cmd[-1]=='_serve' and
                Path(cmd[4]).resolve()==wanted):return True
        except (psutil.Error,AttributeError,OSError):continue
    return False


def start_core(home):
    """Use Core's existing detached process manager; observe an existing job once."""
    from localpilot_service.cli import start, connection, compatible
    if not pending_core(home):
        try:
            start(home,manager='detached')
        except ValueError as error:
            if 'still starting after' not in str(error):raise
    client=connection(home);client.timeout=1
    deadline=time.monotonic()+120
    while True:
        try:
            health=compatible(client)
            if health.get('status')=='ready':return health
        except (OSError,ValueError):pass
        if time.monotonic()>=deadline:raise ValueError('Core 启动结果尚未确认。请在服务诊断中恢复；不会重复启动或重放任务')
        time.sleep(.5)


def compatibility():
    versions = {}
    for name in ('localpilot-agent-service', 'localpilot-companion', 'localpilot-suite'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'NOT_INSTALLED'
    from localpilot_service import VERSION
    from localpilot_service.protocol import API_VERSION
    def release(name):
        match=re.match(r'^(\d+)\.(\d+)\.(\d+)',versions[name])
        return tuple(map(int,match.groups())) if match else (-1,-1,-1)
    return {'versions': versions, 'agent_service_api': API_VERSION,
            'compatible': API_VERSION == '1.0' and VERSION.startswith('5.') and
                (5,0,0)<=release('localpilot-agent-service')<(6,0,0) and
                (0,5,6)<=release('localpilot-companion')<(0,6,0) and
                (0,2,0)<=release('localpilot-suite')<(0,3,0),
            'model_readiness': 'NOT_PROBED'}


def service(home, module, action):
    if module not in {'core', 'companion', 'omlx'} or action not in {'status', 'start', 'stop', 'recover'}:
        raise ValueError('Unsupported service control')
    if module == 'omlx':
        from .product_installer import owned_service
        return owned_service(action)
    from localpilot_service.cli import connection, start, stop, environment
    from localpilot_service.security import private_json
    home = Path(home)
    if not (home / 'connection.json').exists():
        raise ValueError('请先准备本机组件')
    if module == 'core':
        if action == 'stop':
            return stop(home)
        try:
            health = connection(home).request('/healthz')
            if health.get('status') == 'ready':
                return {'status': 'ready', 'version': health.get('version'), 'recovered': False}
        except Exception:
            pass
        if action == 'status':
            return {'status': 'unavailable', 'next': '恢复服务；数据与任务保留'}
        with contextlib.redirect_stdout(io.StringIO()):
            health = start_core(home)
        if health.get('status') != 'ready':
            raise ValueError('Core 尚未就绪，请查看诊断；未重放任何任务')
        return {'status': 'ready', 'version': health.get('version'), 'recovered': True}
    config = home / 'companion.json'
    private_json(config)
    env = {k: v for k, v in environment(home).items()
           if 'OPERATOR' not in k.upper() and 'DEEPSEEK' not in k.upper()}
    command = [sys.executable, '-m', 'companion', '--config', str(config), '--json',
               'start' if action == 'recover' else action]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise ValueError('Companion 操作失败；请查看独立服务诊断。配置与历史已保留')
    value = json.loads(result.stdout)
    if action in {'start','recover'}:
        deadline=time.monotonic()+20
        while value.get('status')=='starting' and time.monotonic()<deadline:
            time.sleep(.5)
            observed=subprocess.run([*command[:-1],'status'],env=env,capture_output=True,text=True,timeout=5)
            if observed.returncode==0:value=json.loads(observed.stdout)
        if value.get('status')!='running':raise ValueError('Companion 尚未就绪，配置与历史已保留；请重新诊断')
    if action=='stop' and value.get('status')!='stopped':raise ValueError('Companion 尚未安全停止，请稍后重新诊断')
    # Return lifecycle information only, never configuration or tokens.
    return {k: value[k] for k in ('status', 'running', 'pid') if k in value}


def diagnostics(home):
    result = {'compatibility': compatibility(), 'services': {}}
    for module in ('core', 'companion', 'omlx'):
        try:
            result['services'][module] = service(home, module, 'status')
        except Exception:
            result['services'][module] = {'status': 'unavailable', 'next': '准备组件或查看安装说明'}
    result['suite'] = 'ready'
    return result

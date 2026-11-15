"""Exercise installed README commands with scripted HTTP replies, not a real model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


environment = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
output.mkdir()
workspace = output / 'workspace'
workspace.mkdir()
(workspace / 'project.md').write_text('Project fact: portable-guide-731.\n')
seen = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        payload = json.dumps({'object': 'list', 'data': [{'id': 'local-model'}]}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        seen.append(body)
        if len(seen) == 1:
            delta, finish = {'content': 'Installed CLI protocol fixture acknowledged.'}, 'stop'
        elif len(seen) == 2:
            delta = {'tool_calls': [{'index': 0, 'id': 'read-installed-file', 'type': 'function',
                'function': {'name': 'read_file', 'arguments': json.dumps({'path': 'project.md'})}}]}
            finish = 'tool_calls'
        else:
            assert any(m.get('role') == 'tool' and 'portable-guide-731' in str(m.get('content'))
                       for m in body['messages']), 'file evidence never reached the provider'
            delta, finish = {'content': 'Read back portable-guide-731 from project.md.'}, 'stop'
        item = {'id': 'scripted-installed-response', 'object': 'chat.completion.chunk',
                'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
        payload = ('data: ' + json.dumps(item) + '\n\ndata: [DONE]\n\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02))
thread.start()
env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME', 'LOCALPILOT_DISABLE_LOCAL_MODELS'}}
env.update(LOCALPILOT_HOME=str(output / 'home'), PYTHONNOUSERSITE='1')
results = []


def command(label, *args):
    result = subprocess.run([environment / 'bin/localpilot', *args], cwd=output, env=env,
                            capture_output=True, text=True, timeout=45)
    (output / (label + '.log')).write_text(result.stdout + result.stderr)
    results.append({'command': label, 'argv': args, 'exit_code': result.returncode})
    if result.returncode:
        raise RuntimeError(label + ' failed; retained output in ' + str(output))
    return result.stdout


try:
    versions = json.loads(command('version', '--version'))
    assert versions['suite'] == '0.2.0b27'
    assert versions['localpilot-agent-service'] == '5.0.0b22'
    assert versions['localpilot-companion'] == '0.5.7b4'
    command('init', 'init', '--workspace', str(workspace), '--model', 'local-model',
            '--base-url', f'http://127.0.0.1:{server.server_port}/v1', '--context-budget', '8192',
            '--model-timeout', '120', '--port', '18769')
    command('start', 'start')
    command('models', 'models')
    answer = command('ask', 'ask', '--allow-local-on-battery', 'Introduce yourself briefly.')
    assert 'Installed CLI protocol fixture acknowledged.' in answer
    task = command('agent', 'agent', '--allow-local-on-battery', 'Read project.md and report its fact.')
    assert 'portable-guide-731' in task
    command('status', 'status')
    command('stop', 'stop')
    command('restart', 'start')
    command('tasks-after-restart', 'tasks')
    assert len(seen) == 3, 'restart replayed a model request'
    result = {'status': 'PASS', 'scope': 'INSTALLED_CLI_SCRIPTED_HTTP_NOT_MODEL_QUALITY',
              'versions': versions, 'commands': results, 'model_requests': len(seen),
              'actual_file_readback': True, 'restart_no_replay': True,
              'model_usage': 'UNKNOWN', 'working_directory': str(output)}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
finally:
    if (output / 'home/connection.json').exists():
        command('final-stop', 'stop')
    server.shutdown()
    thread.join()
    server.server_close()

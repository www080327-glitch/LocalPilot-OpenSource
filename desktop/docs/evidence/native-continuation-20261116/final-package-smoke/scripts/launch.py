import hashlib,json,os,subprocess,time
from pathlib import Path
out=Path('/workspace/scratch/c0f3ec78c621/validation/native-final-smoke-20261116')
command=['bash','/workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/webkit-minimal-overlay-r9/launch-owned-webview-minimal.sh',str(out/'extracted/usr/bin/localpilot-desktop-test'),str(out/'profile-c')]
record={'command':command,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'display':os.environ.get('DISPLAY'),'xdg_session_type':os.environ.get('XDG_SESSION_TYPE'),'webkit_disable_sandbox_present':'WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS' in os.environ}
record['candidate_sha256']=hashlib.sha256(Path(command[2]).read_bytes()).hexdigest()
record['scope']='Validation-only read-only helper overlay with standard bubblewrap private /dev and the single existing X11 auth file read-only at its original path; same final RC9 candidate, no system installation, no WebKit sandbox disable.'
with (out/'native-final-c.log').open('x') as log:
 p=subprocess.Popen(command,stdout=log,stderr=log)
 record['pid']=p.pid
 (out/'native-final-c-process.json').write_text(json.dumps(record,indent=2))
 record['returncode']=p.wait()
 record['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
 (out/'native-final-c-process.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record))

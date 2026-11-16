import hashlib,json,os,subprocess,time
from pathlib import Path
out=Path('/workspace/scratch/c0f3ec78c621/validation/package-b31-b8-b32-LtvhM6/native-smoke')
command=['bash','/workspace/scratch/c0f3ec78c621/validation/package-b31-b8-b32-LtvhM6/native-smoke/launch-pet-overlay.sh',str(out/'extracted/usr/bin/localpilot-desktop-test'),'/workspace/scratch/c0f3ec78c621/native-rc14-l']
record={'command':command,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'display':os.environ.get('DISPLAY'),'xdg_session_type':os.environ.get('XDG_SESSION_TYPE'),'webkit_disable_sandbox_present':'WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS' in os.environ}
record['candidate_sha256']=hashlib.sha256(Path(command[2]).read_bytes()).hexdigest()
record['scope']='Validation-only read-only helper overlay with standard bubblewrap private /dev and the single existing X11 auth file read-only at its original path; final RC14 candidate from clean GitHub commit c5439659a579b2ee9e74fd53e6d3232fe12fb855, no system installation, no WebKit sandbox disable.'
with (out/'native-rc14-l.log').open('x') as log:
 p=subprocess.Popen(command,stdout=log,stderr=log)
 record['pid']=p.pid
 (out/'native-rc14-l-process.json').write_text(json.dumps(record,indent=2))
 record['returncode']=p.wait()
 record['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
 (out/'native-rc14-l-process.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record))

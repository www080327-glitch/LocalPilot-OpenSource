import hashlib,json,os,subprocess,sys,time
from pathlib import Path
base=Path('/workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop')
out=base/'profile-resume-20261116'
name,root=sys.argv[1:]
candidate=base/'native-final-r4-extracted/usr/bin/localpilot-desktop-test'
overlay=out/'launch-alias-runtime-canonical.sh' if name=='r20-a-alias' else (out/'launch-alias-overlay.sh' if name=='r19-a-alias' else base/'webkit-minimal-overlay-r9/launch-owned-webview-minimal.sh')
command=['bash',str(overlay),str(candidate),root]
record={'run':name,'command':command,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'display':os.environ.get('DISPLAY'),'xdg_session_type':os.environ.get('XDG_SESSION_TYPE'),'webkit_disable_sandbox_present':'WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS' in os.environ,'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest()}
with (out/(name+'.log')).open('x') as log:
 p=subprocess.Popen(command,stdout=log,stderr=log)
 record['pid']=p.pid
 (out/(name+'-process.json')).write_text(json.dumps(record,indent=2))
 record['returncode']=p.wait()
 record['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
 (out/(name+'-process.json')).write_text(json.dumps(record,indent=2))
print(json.dumps(record))

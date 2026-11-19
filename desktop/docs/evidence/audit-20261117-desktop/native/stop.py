import hashlib,json,os,signal,sys,time
from pathlib import Path

BASE=Path('/workspace/scratch/c0f3ec78c621/validation/native-audit-20261117')
CANDIDATE=BASE/'extracted/usr/bin/localpilot-desktop-test'
CANDIDATE_SHA='c79066b761da62eb9944ab7f0c42f097035b0a669153ecc3e6a7da41703a24d8'
RUNS={'d':'profile-d'}


def main():
    run=sys.argv[1]
    expected_root=BASE/RUNS[run]
    source=BASE/('native-audit-'+run+'-process.json')
    output=BASE/('native-audit-'+run+'-stop.json')
    record={'run':run,'started_utc':utc(),'signal_sent':False,'scope':'Only SIGTERM the verified UI main process below this run wrapper; no signal is sent to external PIDs or separate services.'}
    if output.exists():
        raise SystemExit('Stop result already exists; refusing to overwrite it')
    try:
        launch=json.loads(source.read_text())
        table=process_table()
        owned=descendants(int(launch['pid']),table)
        ui=verified_ui(launch,expected_root,owned)
        record.update({'wrapper_pid':int(launch['pid']),'ui_pid':ui,'candidate_sha256':CANDIDATE_SHA,'root_match':True,'canonical_test_root':str(expected_root.resolve()),'owned_before':[table[pid] for pid in sorted(owned) if pid in table]})
        os.kill(ui,signal.SIGTERM)
        record['signal_sent']=True
        record['signal_name']='SIGTERM'
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and Path('/proc/'+str(launch['pid'])).exists():
            time.sleep(.2)
        after=process_table()
        record['ui_still_present']=ui in after
        record['owned_remaining']=[after[pid] for pid in sorted(owned) if pid in after]
        updated=json.loads(source.read_text())
        record['launcher_returncode']=updated.get('returncode')
        record['launcher_finished_utc']=updated.get('finished_utc')
        record['status']='STOPPED' if not record['ui_still_present'] and not record['owned_remaining'] else 'OWNED_PROCESSES_REMAIN'
    except (OSError,ValueError,KeyError,RuntimeError) as error:
        record['status']='ERROR_AFTER_SIGNAL' if record['signal_sent'] else 'ABORTED_IDENTITY'
        record['error_class']=type(error).__name__
        record['error']=str(error)
    record['finished_utc']=utc()
    output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))
    raise SystemExit(0 if record['status']=='STOPPED' else 1)


def utc():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())


def process_table():
    rows={}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            status={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (path/'status').read_text().splitlines() if line.startswith(('Name:','Pid:','PPid:','State:'))}
            rows[int(path.name)]={'pid':int(path.name),'ppid':int(status['PPid']),'name':status['Name'],'state':status['State']}
        except (OSError,ValueError,KeyError):
            continue
    return rows


def descendants(root,table):
    owned={root}
    while True:
        expanded=owned|{pid for pid,row in table.items() if row['ppid'] in owned}
        if expanded==owned:
            return owned
        owned=expanded


def verified_ui(launch,expected_root,owned):
    if launch.get('returncode') is not None:
        raise RuntimeError('Recorded run has already finished')
    if launch.get('candidate_sha256')!=CANDIDATE_SHA or hashlib.sha256(CANDIDATE.read_bytes()).hexdigest()!=CANDIDATE_SHA:
        raise RuntimeError('Candidate identity does not match this profile qualification')
    if os.readlink('/proc/'+str(launch['pid'])+'/exe')!='/usr/bin/bwrap':
        raise RuntimeError('Recorded wrapper is not the expected bubblewrap executable')
    matches=[]
    for pid in owned:
        try:
            if os.readlink('/proc/'+str(pid)+'/exe')!=str(CANDIDATE.resolve()):
                continue
            entries=Path('/proc/'+str(pid)+'/environ').read_bytes().split(b'\0')
            value=next((entry.split(b'=',1)[1] for entry in entries if entry.startswith(b'LP_INSTALL_TEST_ROOT=')),None)
            if value is None or Path(os.fsdecode(value)).resolve()!=expected_root.resolve():
                raise RuntimeError('Owned candidate environment does not match the expected profile root')
            matches.append(pid)
        except FileNotFoundError:
            continue
    if len(matches)!=1:
        raise RuntimeError('Expected exactly one owned UI process matching candidate and profile')
    return matches[0]


if __name__=='__main__':
    main()

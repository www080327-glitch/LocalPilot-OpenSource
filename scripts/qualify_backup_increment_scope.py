"""Synthetic files only; no original state or key contents are logged.

Uses an explicit local age identity via its location metadata. Both successful
and rejected outputs are retained in a new directory; no original data removed.
"""
from pathlib import Path
import argparse,json,os,hashlib
from unittest.mock import patch
from localpilot_encrypted_backup import create,restore
parser=argparse.ArgumentParser(description='Synthetic incremental directory scope + actual age/restore qualification')
parser.add_argument('--out',type=Path,required=True);parser.add_argument('--age',type=Path,required=True);parser.add_argument('--key-location',type=Path,required=True)
a=parser.parse_args();area=a.out.expanduser().resolve();area.mkdir(mode=0o700,parents=True,exist_ok=False);w=Path(__file__).resolve().parents[1];root=area/'source';(root/'selected/empty').mkdir(mode=0o700,parents=True);(root/'unselected').mkdir(mode=0o700);file=root/'selected/marker.txt';file.write_text('synthetic bounded increment\n');file.chmod(0o600);inv=area/'inventory';inv.mkdir(mode=0o700);s=file.stat();description={'roots':[{'id':0,'path':str(root)}],'directory_paths':[str(root/'selected'),str(root/'selected/empty')]};(inv/'inventory.json').write_text(json.dumps(description));(inv/'files.jsonl').write_text(json.dumps({'root':0,'relative':'selected/marker.txt','sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'mtime_ns':s.st_mtime_ns})+'\n');(inv/'git-worktrees.json').write_text('[]');(inv/'owned-models.json').write_text('[]');location=json.loads(a.key_location.read_text());age=a.age.resolve(strict=True)
with patch('localpilot_encrypted_backup.os.walk',side_effect=AssertionError('Increment must not walk source roots')):
 create(inv,area/'encrypted',age,location['public_recipient'],Path(location['path']))
restore(area/'encrypted',area/'restored',age,Path(location['path']))
assert (area/'restored/roots/000/selected/marker.txt').read_bytes()==file.read_bytes();assert (area/'restored/roots/000/selected/empty').is_dir();assert not (area/'restored/roots/000/unselected').exists()
for index,bad in enumerate([str(root.parent),str(root/'../escape')]):
 description['directory_paths']=[bad];(inv/'inventory.json').write_text(json.dumps(description))
 try:create(inv,area/('invalid-'+str(index)),age,location['public_recipient'],Path(location['path']))
 except ValueError:pass
 else:raise AssertionError('Outside directory accepted')
report={'status':'PASS','no_source_walk':True,'selected_file_and_empty_directory_restored':True,'unselected_directory_not_archived':True,'outside_and_parent_traversal_rejected':True,'private_key_printed_or_uploaded':False};(area/'qualification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

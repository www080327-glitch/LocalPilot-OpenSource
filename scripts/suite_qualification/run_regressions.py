import importlib.abc,sys,unittest,time,json,resource,os,hashlib
from pathlib import Path
class NoModel(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'mlx','mlx_lm','mlx_vlm','torch','transformers'}:raise ImportError('Local models disabled during battery qualification')
sys.meta_path.insert(0,NoModel())
if __name__ == '__main__':
 root=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();sys.path.insert(0,str(root));os.chdir(root)
 class Throttled(unittest.TextTestResult):
  def startTest(self,test):time.sleep(.025);super().startTest(test)
 def source_hashes():
  result={}
  folders=['agent','computer','localpilot_api','localpilot_service','tests','benchmarks'] if (root/'localpilot_service').is_dir() else ['companion']
  for folder in folders:
   for path in (root/folder).rglob('*'):
    if path.is_file() and path.suffix in {'.py','.json','.toml'} and not any(x in path.parts for x in ['evidence','.data','__pycache__','build']):
     result[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
  return result
 before=source_hashes()
 suite=unittest.defaultTestLoader.discover(sys.argv[3] if len(sys.argv)>3 else 'tests',top_level_dir=str(root))
 t=time.monotonic()
 with out.with_suffix('.log').open('w') as log:r=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Throttled).run(suite)
 out.with_suffix('.json').write_text(json.dumps(dict(tests=r.testsRun,failures=len(r.failures),errors=len(r.errors),skips=len(r.skipped),elapsed_seconds=time.monotonic()-t,cpu_seconds=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,local_model_imports_blocked=True,source_unchanged=(before==source_hashes()),source_files=len(before)),indent=2))
 out.with_name(out.name+'-source-hashes.json').write_text(json.dumps(before,indent=2))
 print(out.with_suffix('.json').read_text());sys.exit(not r.wasSuccessful())

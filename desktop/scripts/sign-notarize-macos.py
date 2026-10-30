"""Explicit Developer ID workflow; diagnose is read-only and default.

Uses only a user-supplied valid identity and existing notarytool profile. It
copies a regular-ID APP to a new output slot; it never signs the daily APP.
"""
import argparse,hashlib,json,plistlib,shutil,subprocess,sys
from pathlib import Path

def run(argv):return subprocess.check_output(list(map(str,argv)),stderr=subprocess.STDOUT,text=True)
def main():
 p=argparse.ArgumentParser();p.add_argument('--app',type=Path);p.add_argument('--output',type=Path);p.add_argument('--identity');p.add_argument('--notary-profile');p.add_argument('--execute',action='store_true');a=p.parse_args()
 identities=run(['security','find-identity','-v','-p','codesigning']);diagnostic={'developer_id_available':'Developer ID Application:' in identities,'notarization':'NOT_RUN','gatekeeper_bypass':False,'default':'diagnose_only'}
 if not a.execute:print(json.dumps(diagnostic,indent=2));return
 if not a.identity or not a.identity.startswith('Developer ID Application:') or ('"'+a.identity+'"') not in identities:raise SystemExit('An explicitly authorized valid Developer ID Application identity is required')
 if not a.notary_profile or not a.app or not a.output:raise SystemExit('Provide an APP, new output directory and an authorized existing notarytool profile')
 source=a.app.resolve(strict=True);info=plistlib.loads((source/'Contents/Info.plist').read_bytes())
 if info['CFBundleIdentifier']!='io.localpilot.desktop':raise SystemExit('Formal distribution requires a separately qualified regular-ID build; test APP refused')
 if source==Path.home()/'Applications/LocalPilot.app':raise SystemExit('Daily installation is not a signing input; use an archive/build slot')
 a.output.mkdir(parents=True,exist_ok=False);app=a.output/'LocalPilot.app';run(['ditto',source,app]);steps=[]
 magic={b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'}
 for path in sorted(app.rglob('*'),key=lambda x:len(x.parts),reverse=True):
  if path.is_symlink() or not path.is_file():continue
  with path.open('rb') as f:header=f.read(4)
  if header in magic:run(['codesign','--force','--sign',a.identity,'--options','runtime','--timestamp',path]);steps.append(str(path.relative_to(app)))
 for bundle in sorted([p for p in app.rglob('*') if p.suffix in {'.app','.framework','.xpc'} and p.is_dir()],key=lambda p:len(p.parts),reverse=True):run(['codesign','--force','--sign',a.identity,'--options','runtime','--timestamp',bundle])
 run(['codesign','--force','--sign',a.identity,'--options','runtime','--timestamp',app]);run(['codesign','--verify','--deep','--strict',app])
 archive=a.output/'notarization-input.zip';run(['ditto','-c','-k','--keepParent',app,archive])
 def notarize(path,label):
  result=json.loads(run(['xcrun','notarytool','submit',path,'--keychain-profile',a.notary_profile,'--wait','--output-format','json']));(a.output/(label+'.json')).write_text(json.dumps(result,indent=2)+'\n')
  if result.get('status')!='Accepted':raise SystemExit('Notarization did not return Accepted; retained diagnostics, no release')
 notarize(archive,'app-notary');run(['xcrun','stapler','staple',app]);run(['xcrun','stapler','validate',app]);run(['spctl','--assess','--type','execute','--verbose=4',app])
 image=a.output/'LocalPilot.dmg';run(['hdiutil','create','-volname','LocalPilot','-srcfolder',app,'-format','UDZO',image]);run(['codesign','--sign',a.identity,'--timestamp',image]);notarize(image,'dmg-notary');run(['xcrun','stapler','staple',image]);run(['xcrun','stapler','validate',image]);run(['hdiutil','verify',image])
 final=a.output/'LocalPilot.app.zip';run(['ditto','-c','-k','--keepParent',app,final]);report={'status':'SIGNED_AND_NOTARIZED_PENDING_DOWNLOAD_CLEAN_MAC_ACCEPTANCE','nested_macho':steps,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [final,image]},'public_release_created':False};(a.output/'SIGNING.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()

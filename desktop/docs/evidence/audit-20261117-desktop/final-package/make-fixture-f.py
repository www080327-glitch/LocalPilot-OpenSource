from pathlib import Path
from PIL import Image,ImageDraw
import json,hashlib,os
base=Path('/workspace/scratch/c0f3ec78c621/validation/package-b27-b8-b32-Azb7vG/native-smoke')
root=Path('/workspace/scratch/c0f3ec78c621/native-rc10-f')
root.mkdir(mode=0o700)
client=root/'client'; client.mkdir(mode=0o700)
def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.chmod(0o600)
save(root/'test-owner.json',{'purpose':'LocalPilot installation E2E','task':'native desktop audit 20261117','owner':'native_completion','fixture':'synthetic geometry only, no personal character or accounts'})
colors=[(35,145,168,255),(80,154,113,255),(166,116,51,255),(127,96,171,255),(63,120,193,255),(176,79,102,255),(89,156,174,255),(179,126,72,255)]
# Eight independently numbered geometric frames, eleven rows: a private test fixture, not product artwork.
atlas=Image.new('RGBA',(8*64,11*64))
d=ImageDraw.Draw(atlas)
for row in range(11):
    for col in range(8):
        x,y=col*64,row*64
        d.rounded_rectangle((x+8,y+5,x+55,y+58),radius=14,fill=colors[col])
        d.ellipse((x+19,y+19,x+24,y+24),fill='white');d.ellipse((x+39,y+19,x+44,y+24),fill='white')
        d.text((x+29,y+35),str(col),fill='white')
path=client/'pet-sprite.webp';atlas.save(path,'WEBP',lossless=True);path.chmod(0o600)
identity='deepseek-audit-geometry-fixture'
save(client/'pet-asset-v1.json',{'version':1,'id':identity,'label':'动画验证夹具','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'usage':'isolated synthetic validation fixture','redistribution':'not_product_art'})
pack=client/'edge-packs'/identity;pack.mkdir(mode=0o700,parents=True);pack.parent.chmod(0o700)
poses=Image.new('RGBA',(96*3,96*3));d=ImageDraw.Draw(poses)
names=['TOP_LEFT','TOP_RIGHT','LEFT_EDGE','RIGHT_EDGE','BOTTOM_LEFT','BOTTOM_RIGHT','RETRACTED','WORKING','IDLE_POT'];rects={}
for i,name in enumerate(names):
    x,y=i%3*96,i//3*96
    d.rounded_rectangle((x+8,y+6,x+87,y+89),radius=23,fill=colors[i%8])
    d.ellipse((x+27,y+26,x+35,y+34),fill='white');d.ellipse((x+61,y+26,x+69,y+34),fill='white')
    d.text((x+45,y+53),str(i),fill='white');rects[name]=[x,y,96,96]
path=pack/'poses.png';poses.save(path);path.chmod(0o600)
save(pack/'pack.json',{'id':identity,'version':1,'poses':rects,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'presentation':{'gripContactX':[0.045,0.955]},'extras':{}})
save(base/'fixture-f-manifest.json',{'purpose':'native movement/opacity/crop validation, no product art changes','frame_count_per_direction':8,'edge_pose_count':9,'comic_extra_absent':True,'files':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in client.rglob('*') if p.is_file()}})
print(root)

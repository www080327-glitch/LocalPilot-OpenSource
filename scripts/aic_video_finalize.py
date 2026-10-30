"""Keep the live recording at real time; add disclosed synthetic narration."""
import json
from pathlib import Path
import re
import subprocess
import wave

ROOT=Path(__file__).resolve().parents[1];M=ROOT/'output/aic-20261029/materials';M.mkdir(parents=True,exist_ok=True)
FF=ROOT/'.aic-runtime/media-deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
record=json.loads((ROOT/'.aic-runtime/video-recording6/recording.json').read_text())
scenes=json.loads((ROOT/'.aic-runtime/narration/scenes.json').read_text());duration=244
concat=ROOT/'.aic-runtime/video-recording6/frames.concat'
records=[]
for i,frame in enumerate(record['frames']):
    records+=['file '+repr(frame['path'])]
    if i+1<len(record['frames']):records+=['duration '+str(record['frames'][i+1]['seconds']-frame['seconds'])]
records+=['file '+repr(record['frames'][-1]['path'])];concat.write_text('\n'.join(records)+'\n')
command=[str(FF),'-hide_banner','-n','-f','concat','-safe','0','-i',str(concat)]
filters=[]
for i,(start,text) in enumerate(scenes):
    audio=ROOT/f'.aic-runtime/narration/{i}.wav'
    with wave.open(str(audio)) as w:length=w.getnframes()/w.getframerate()
    next_start=scenes[i+1][0] if i+1<len(scenes) else duration
    if length>next_start-start:raise ValueError('Narration overlaps the next chapter')
    command+=['-i',str(audio)];filters.append(f'[{i+1}:a]adelay={start*1000}:all=1[a{i}]')
filters.append(''.join(f'[a{i}]' for i in range(len(scenes)))+f'amix=inputs={len(scenes)}:normalize=0,apad,atrim=duration={duration}[audio]')
out=M/'localpilot-真实演示.mp4'
command+=['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[audio]','-vf','fps=10,tpad=stop_mode=clone:stop_duration=4',
    '-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','25','-threads','1','-pix_fmt','yuv420p','-c:a','aac','-b:a','96k','-movflags','+faststart',str(out)]
subprocess.run(command,check=True)
if not 180<=duration<=300 or out.stat().st_size>300_000_000:raise ValueError('AIC video size/time gate failed')
def stamp(seconds):
    i=int(seconds*1000);return f'{i//3600000:02}:{i//60000%60:02}:{i//1000%60:02},{i%1000:03}'
subtitles=[]
for i,(start,text) in enumerate(scenes):
    with wave.open(str(ROOT/f'.aic-runtime/narration/{i}.wav')) as w:length=w.getnframes()/w.getframerate()
    subtitles.append(f'{i+1}\n{stamp(start)} --> {stamp(start+length)}\n{text}\n')
(M/'localpilot-旁白字幕.srt').write_text('\n'.join(subtitles))
(M/'视频说明.txt').write_text('实时 Core SDK 事件视图；不是原生桌面 UI 验收。\n原始浏览器画面约 3 fps 采样，按真实时间间隔等速合成 10 fps；未剪去模型等待制造加速，尾帧补足音轨。\n旁白由 macOS Tingting 语音合成；原始画面序列、事件时序及前期失败记录保留。\n所有本地文件均为本轮合成夹具；本视频没有启动本地语言模型。\n')
validation={'duration_seconds':duration,'bytes':out.stat().st_size,'resolution':'1280x720','fps':10,
    'real_time_recording':True,'synthetic_narration':True,'scope':record['scope'],'original_recording_seconds':record['durationSeconds']}
(ROOT/'output/aic-20261029/video-validation.json').write_text(json.dumps(validation,indent=2))
qa=ROOT/'.aic-runtime/qa/video';qa.mkdir(parents=True,exist_ok=True)
for second in [5,25,60,117,160,190,220]:
    subprocess.run([str(FF),'-hide_banner','-loglevel','error','-n','-ss',str(second),'-i',str(out),'-frames:v','1',str(qa/f'{second}.png')],check=True)
print(json.dumps(validation))

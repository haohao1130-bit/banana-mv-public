"""Optional aligned editorial effects stem; never resynthesize or replace music."""
import math
import subprocess
from pathlib import Path


def samples(path):
    import numpy as np
    result=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-t','301','-vn',
                           '-ac','1','-ar','16000','-f','f32le','pipe:1'],capture_output=True,timeout=120)
    if result.returncode:raise ValueError('音效軌無法解碼。')
    data=np.frombuffer(result.stdout,dtype='<f4')
    if not len(data) or not np.isfinite(data).all():raise ValueError('音效素材無效。')
    return data


def validate_effects(path,song,seconds):
    import numpy as np
    data=samples(path)
    if abs(len(data)/16000-seconds)>1/24:raise ValueError('音效／配音軌須與歌曲同起點、同長度，保留靜音。')
    peak=float(np.max(np.abs(data)))
    hop=800;count=math.ceil(len(data)/hop)
    padded=np.pad(data,(0,count*hop-len(data)))
    rms=np.sqrt(np.mean(padded.reshape(-1,hop).astype('float64')**2,axis=1))
    active=rms>max(10**(-48/20),float(np.max(rms))*10**(-35/20))
    coverage=float(np.mean(active));longest=run=0
    for value in active:
        run=run+1 if value else 0;longest=max(longest,run)
    if coverage>.25 or longest*.05>3.05:
        raise ValueError('音效過密：有聲時間最多佔全曲 25%，單次最多 3 秒；請移除持續環境音與重複鋪底。')
    music=samples(song);music_rms=float(np.sqrt(np.mean(music.astype('float64')**2)))
    # An effect's mono peak stays below a quarter of the song's RMS, with a
    # further absolute -15dB gain ceiling. Music itself is not ducked/normalized.
    gain=min(.18,music_rms*.25/max(peak,1e-9)) if peak>.0001 else 0.
    return {'gain':round(gain,8),'coverage':round(coverage,4),'max_event_seconds':round(longest*.05,2),
            'policy':'sparse_external_stem_v1','auto_generated':False}


def effect_mix(gain):
    if not isinstance(gain,(int,float)) or not math.isfinite(gain) or not 0<=gain<=.18:
        raise ValueError('音效混音音量無效。')
    return (f'[2:a:0]aformat=channel_layouts=mono,volume={gain:.8f},apad[fx];'
            '[1:a:0][fx]amix=inputs=2:duration=first:normalize=0,'
            'alimiter=limit=0.98:level=0:latency=1[mixed]')

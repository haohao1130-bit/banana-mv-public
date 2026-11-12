"""Pure workflow construction and frame-accurate media assembly; no GPU imports."""
import json
import math
import re
import subprocess
from pathlib import Path

FPS = 24
MAX_PICTURES = 9
MAX_SONG_SECONDS = 300
MODELS = {
    'unet': 'Minimax-h3_Singularity_x_10Eros-Max_PRISM_int8.safetensors',
    'clip': 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',
    'video_vae': 'minimax_h3_video_vae_int8_convrot.safetensors',
    'audio_vae': 'minimax_h3_audio_vae_fp32.safetensors',
}
MOTION_LORAS = {'combat': 'H3_Combat_V2.safetensors', 'repair': 'Motion_Repair.safetensors'}


def command(args):
    # ffprobe emits UTF-8 JSON. Windows' default subprocess codec can differ
    # (e.g. cp950), unlike the working local VNext subprocess contract.
    result = subprocess.run([str(a) for a in args], capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError((result.stderr or '')[-2500:] or f'Command failed: {args[0]}')
    if result.stdout is None:
        raise RuntimeError(f'{args[0]} returned no captured output; check the selected Python and executable.')
    return result.stdout


def probe(path):
    raw = command(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path])
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError('ffprobe returned no JSON for media upload; verify ffprobe on PATH and the source audio file.')
    try:
        info = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError('ffprobe returned invalid JSON for media upload: '+str(error)) from error
    if not isinstance(info, dict) or not isinstance(info.get('streams'), list):
        raise RuntimeError('ffprobe media metadata is missing its streams list.')
    return info


def duration(path):
    info = probe(path)
    return float(info['format']['duration'])


def source_audio_duration(path):
    """Use decoded samples for song/vocal timelines, not container padding.

    Match the analysis decoder rate. A 301-second sentinel bounds memory and
    still lets segments() reject songs over the supported five minutes.
    """
    result = subprocess.run(['ffmpeg','-v','error','-i',str(path),'-t','301',
                             '-map','0:a:0','-vn','-ac','1','-ar','16000',
                             '-f','s16le','pipe:1'],capture_output=True,timeout=120)
    if result.returncode:
        raise ValueError('無法讀取歌曲實際音軌：'+result.stderr.decode(errors='replace')[-1000:])
    seconds = len(result.stdout)/(16000*2)
    if seconds <= 0:
        raise ValueError('歌曲沒有可解碼的音訊。')
    return seconds


def segments(seconds, segment_seconds=15):
    if not math.isfinite(seconds) or not 0 < seconds <= MAX_SONG_SECONDS:
        raise ValueError('音樂長度須大於 0、最多 300 秒（5 分鐘）。')
    if not 4 <= segment_seconds <= 15:
        raise ValueError('分段長度須為 4–15 秒。')
    total = math.ceil(seconds * FPS - 1e-8)
    chunk = round(segment_seconds * FPS)
    return [{'index': i, 'start_frame': start, 'frames': min(chunk, total-start),
             'start': start/FPS, 'seconds': min(chunk, total-start)/FPS,
             # Short final windows are padded for generation, then trimmed before assembly.
             'model_frames': align_frames(max(124, min(chunk, total-start)))}
            for i, start in enumerate(range(0, total, chunk))]


def align_frames(frames):
    return 5 + math.ceil((max(5, frames)-5)/17)*17


OUTPUT_SIZES = {'16:9': (1280,720), '9:16': (720,1280), '4:5': (720,900), '1:1': (720,720)}


# Existing width requests identify the preset, so saved 720p projects remain compatible.
OUTPUT_SIZE_PRESETS = {
    '720p': OUTPUT_SIZES,
    '480p': {'16:9': (854,480), '9:16': (480,854), '4:5': (480,600), '1:1': (480,480)},
}


def output_dimensions(aspect, width=None):
    if aspect not in OUTPUT_SIZES:
        raise ValueError('不支援的比例。')
    if width is None:
        return OUTPUT_SIZES[aspect]
    for sizes in OUTPUT_SIZE_PRESETS.values():
        if width == sizes[aspect][0]:
            return sizes[aspect]
    raise ValueError(f'不支援的橫向寬度；{aspect} 請選擇 720P 或 480P 預設尺寸。')


def dimensions(aspect, width=None):
    width, height = output_dimensions(aspect, width)
    # Generate enough pixels, then crop only the alignment padding at final delivery.
    return math.ceil(width/32)*32, math.ceil(height/32)*32


def audio_window(source, dest, start, seconds):
    command(['ffmpeg', '-y', '-v', 'error', '-i', source, '-map', '0:a:0', '-ss', f'{start:.9f}',
             '-t', f'{seconds:.9f}', '-vn', '-af', 'apad', '-ar', '32000', '-ac', '2',
             '-c:a', 'pcm_s16le', dest])


def trim_video(source, dest, frame_count, *, skip_frames=0):
    """Trim exact delivered frames; skip anchored overlap only in five-frame mode."""
    if frame_count < 1 or skip_frames < 0:
        raise ValueError('影格裁切參數無效。')
    command(['ffmpeg', '-y', '-v', 'error', '-i', source, '-an', '-vf',
             f'fps={FPS},trim=start_frame={skip_frames}:end_frame={skip_frames+frame_count},setpts=PTS-STARTPTS',
             '-frames:v', str(frame_count), '-c:v', 'libx264', '-threads', '1',
             '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', dest])
    video = next(s for s in probe(dest)['streams'] if s['codec_type']=='video')
    if int(video.get('nb_frames', -1)) != frame_count:
        raise RuntimeError('模型輸出影格不足，已停止合成，避免歌曲錯拍。')


def last_frame(source, dest):
    count = int(next(s for s in probe(source)['streams'] if s['codec_type']=='video')['nb_frames'])
    command(['ffmpeg', '-y', '-v', 'error', '-i', source, '-vf', f'select=eq(n\\,{count-1})',
             '-frames:v', '1', '-update', '1', dest])


def last_frames(source, dest_pattern, count=5):
    """Export chronological tail frames to an ffmpeg %%02d PNG pattern."""
    frames = int(next(s for s in probe(source)['streams'] if s['codec_type']=='video')['nb_frames'])
    if count != 5 or frames < count:
        raise ValueError('末五幀接續需要至少五個完整影格。')
    pattern = str(dest_pattern)
    if '%02d' not in pattern:
        raise ValueError('末五幀輸出檔名必須包含 %02d。')
    command(['ffmpeg', '-y', '-v', 'error', '-i', source, '-vf',
             f'select=gte(n\\,{frames-count})', '-vsync', '0',
             '-frames:v', str(count), pattern])
    paths = [Path(pattern % n) for n in range(1, count+1)]
    if any(not p.is_file() or p.stat().st_size == 0 for p in paths):
        raise RuntimeError('最後五幀抽取不完整，停止接續，避免傳入錯誤動作。')
    return paths


def assemble(parts, song, dest, seconds, output_size=None, effects=None):
    # Paths are generated job-local names; JSON quoting is not shell quoting.
    # ffconcat syntax has its own quote escaping, independently of shell arguments.
    listing = Path(dest).with_suffix('.ffconcat')
    listing.write_text('ffconcat version 1.0\n' + ''.join(
        "file '" + str(Path(p).resolve()).replace("'", "'\\''") + "'\n" for p in parts), encoding='utf-8')
    video_options = ['-c:v', 'copy']
    if output_size:
        width, height = output_size
        source = next(s for s in probe(parts[0])['streams'] if s['codec_type']=='video')
        if source['width'] < width or source['height'] < height:
            raise RuntimeError('生成尺寸低於要求的輸出尺寸，停止合成；不以放大冒充生成解析度。')
        if (source['width'], source['height']) != (width, height):
            video_options = ['-vf', f'crop={width}:{height}', '-c:v', 'libx264',
                             '-threads', '1', '-crf', '18', '-pix_fmt', 'yuv420p']
    audio_options=['-map','1:a:0']
    extra=[]
    if effects:
        from banana_mv.sound_effects import effect_mix
        extra=['-i',effects['path']]
        audio_options=['-filter_complex',effect_mix(effects['gain']),'-map','[mixed]']
    command(['ffmpeg', '-y', '-v', 'error', '-safe', '0', '-f', 'concat', '-i', listing,
             '-i', song, *extra, '-map', '0:v:0', *audio_options, *video_options,
             '-c:a', 'aac', '-b:a', '192k', '-t', f'{seconds:.9f}', '-movflags', '+faststart', dest])


def reference_images(images, continuation=False):
    """Keep the legacy single-image API; reserve one picture for a continuation keyframe."""
    images = [images] if isinstance(images, str) else images
    limit = MAX_PICTURES - int(continuation)
    if not isinstance(images, (list, tuple)) or not 1 <= len(images) <= limit:
        raise ValueError(f'獨立版最多 9 張；接續版預留末幀，最多 8 張。此次可用 1–{limit} 張。')
    if any(not isinstance(x, str) or not x.strip() for x in images):
        raise ValueError('參考圖片清單含無效項目。')
    return list(images)


def map_image_mentions(prompt, image_count, continuation=False):
    """UI @圖片N always refers to uploaded images, independently of internal keyframes."""
    def replace(match):
        n = int(match[1])
        if not 1 <= n <= image_count:
            raise ValueError(f'找不到 @圖片{n}，目前只有 {image_count} 張參考圖。')
        return f'<Picture {n + int(continuation)}>'
    return re.sub(r'@(?:圖片|图片|image)\s*(\d+)', replace, prompt, flags=re.I)


class MediaReferenceError(ValueError):
    """A prompt names media that is not actually connected."""


def normalize_mv_prompt(prompt, picture_count):
    """This runner has pictures and one audio, never connected reference videos."""
    if not prompt or not prompt.strip():
        raise ValueError('提示詞改寫回傳空白，請關閉改寫或檢查本地模型。')
    def replace(match):
        kind, ordinal = match[1].lower(), int(match[2])
        if kind == 'video':
            return 'the generated clip'
        limit = 1 if kind == 'audio' else picture_count
        if not 1 <= ordinal <= limit:
            raise MediaReferenceError(f'提示詞引用不存在的 {kind} {ordinal}；目前只有 {picture_count} 張圖片及 1 段音訊。')
        return f'<{"Audio" if kind == "audio" else "Picture"} {ordinal}>'
    return re.sub(r'<\s*(Image|Picture|Video|Audio)\s*(\d+)\s*>', replace, prompt, flags=re.I)


def enforce_face_identity(prompt, main_picture):
    """Final text guidance only; bind identity to the original, not a generated keyframe."""
    if isinstance(main_picture, bool) or not isinstance(main_picture, int) or main_picture < 1:
        raise ValueError('主角參考圖片編號必須為正整數。')
    # Replace only our own block, so repeated finalization cannot grow the prompt.
    prompt = re.sub(r'\n*\[BANANA_FACE_IDENTITY_V1\].*?\[/BANANA_FACE_IDENTITY_V1\]',
                    '', prompt, flags=re.S).rstrip()
    return prompt + (
        '\n\n[BANANA_FACE_IDENTITY_V1]\n'
        f'<Subject 1> is the same individual shown in <Picture {main_picture}>, the original performer reference. '
        'Preserve the original facial geometry, eye shape, nose structure, lips, jawline and '
        'distinctive facial features across cuts, expressions and action sequences. '
        'This locks facial identity only. Hairstyle, clothing, makeup, injuries and other mutable '
        'appearance follow the user instructions and current persistent scene state, not the initial '
        'reference outfit. Preserve their current state when no change is requested. '
        'Do not redesign, recast, beautify, replace or morph the face, or blend identities from other references. '
        'Allow natural expressions, head turns, profiles, dynamic movement, varied shot sizes and cinematic camera angles. '
        'Priority: performer identity, source-song synchronization and lip sync, action and story events, '
        'camera and editing, then visual effects. Identity consistency does not require fixed poses or frontal close-ups.\n'
        '[/BANANA_FACE_IDENTITY_V1]')


def fallback_prompt(prompt, continuation=False, lyrics='', image_count=1, scene_aware=False):
    reference_images(['reference'] * image_count, continuation)
    prompt = map_image_mentions(prompt, image_count, continuation)
    who = 2 if continuation else 1
    boundary = '<Picture 1> is the exact first frame, continuing the previous clip.\n' if continuation else ''
    extra = ''.join(f'<Picture {n + int(continuation)}> is uploaded reference image {n}; '
                    'use only the identity, angle, environment or object specified by the user. '
                    'Do not automatically add performers or blend distinct people.\n'
                    for n in range(2, image_count + 1))
    opening = ('[Shot 1] Follow the allocated event and its actual scene. Singing shots use the user-designated '
               'vocal performer(s) with visible synchronized mouth movement; non-singing roles and action scenes '
               'remain non-singing as specified. Do not add an opening singing shot to an action-first brief. '
               if scene_aware else '[Shot 1] The performer sings in a medium close-up with visible unobstructed mouth, '
               'natural expressive motion, and plausible lip movements synchronized to <Audio 1>. ')
    return (f'subject_definitions:\n<Subject 1> is the adult performer in <Picture {who}>.\n' + boundary +
            extra +
            f'\nsummary:\nA music video performance synchronized to <Audio 1>. {prompt}\n'
            f'\nretention_analysis:\n<Picture {who}>: fully_preserved — retain performer identity and clothing.\n'
            '<Audio 1>: fully_copy — preserve the source vocal timing and phrasing.\n'
            '\ndetailed_description:\n' + opening
            + (f'Known exact lyrics: <d>{lyrics}</d>. ' if lyrics else 'Do not invent quoted lyrics. ') +
            f'{prompt}\n\noverall_soundscape:\nThe provided source audio.\n'
            '\nnon_diegetic_music:\nUse the provided soundtrack; do not compose a replacement song.')


def build_workflow(image, audio, width, height, model_frames, prompt, seed,
                   first_frame=None, steps=8, *, acceleration=True, motion_lora=True,
                   director_mode='performance', intensity='high',
                   kitchen_attention=None, sparse_attention=None, guide_frames=None):
    """Preserve source-audio sampling; optional model patches precede SigmaShift."""
    if intensity not in ('normal', 'high', 'extreme'):
        raise ValueError('未知動作強度')
    # Legacy acceleration toggled both patches. Explicit fields override it independently.
    kitchen_attention = acceleration if kitchen_attention is None else kitchen_attention
    sparse_attention = acceleration if sparse_attention is None else sparse_attention
    if not isinstance(kitchen_attention, bool) or not isinstance(sparse_attention, bool):
        raise ValueError('注意力開關必須為布林值。')
    if guide_frames is not None:
        if not first_frame or len(guide_frames) != 5 or any(not isinstance(f, str) or not f for f in guide_frames):
            raise ValueError('末五幀引導需要五張依時間排序的 PNG 與首幀。')
        if guide_frames[0] != first_frame:
            raise ValueError('五幀引導起點必須與接續首幀相同。')
    images = reference_images(image, bool(first_frame))
    def node(kind, **inputs):
        return {'class_type': kind, 'inputs': inputs}
    w = {
        '1': node('UNETLoader', unet_name=MODELS['unet'], weight_dtype='default'),
        '2': node('CLIPLoader', clip_name=MODELS['clip'], type='minimax', device='default'),
        '3': node('VAELoader', vae_name=MODELS['video_vae']),
        '4': node('VAELoader', vae_name=MODELS['audio_vae']),
        '5': node('LoadImage', image=images[0]),
        '6': node('LoadAudio', audio=audio),
        '7': node('MiniMaxH3AudioConditioningT8', clip=['2',0], video_vae=['3',0], audio_vae=['4',0],
                  prompt=prompt, width=width, height=height, length=model_frames,
                  task_type='Hybrid' if first_frame else 'Ref2VA', audio_mode='lock_source',
                  audio_denoise_strength=0.0, add_source_as_reference=True,
                  prompt_primary_audio_ordinal=1, strict_prompt_tags=True,
                  ref_image_size='match', reference_video_policy='official_2_to_15s',
                  drive_audio=['6',0], **{'ref_images.ref_image_0':['5',0]}),
        '8': node('MiniMaxH3SigmaShift', model=['1',0], shift_video=12.0, shift_audio=3.0),
        '9': node('BasicGuider', model=['8',0], conditioning=['7',0]),
        '10': node('RandomNoise', noise_seed=seed),
        '11': node('KSamplerSelect', sampler_name='euler'),
        '12': node('BasicScheduler', model=['8',0], scheduler='simple', steps=steps, denoise=1.0),
        '13': node('SamplerCustomAdvanced', noise=['10',0], guider=['9',0], sampler=['11',0],
                   sigmas=['12',0], latent_image=['7',1]),
        '14': node('VAEDecode', samples=['13',0], vae=['3',0]),
        '15': node('CreateVideo', images=['14',0], audio=['7',2], fps=float(FPS)),
        '16': node('SaveVideo', video=['15',0], filename_prefix='BananaMV/segment',
                   format='mp4', **{'format.codec':'h264'}),
    }
    for i, filename in enumerate(images[1:], 1):
        key = f'ref_{i}'
        w[key] = node('LoadImage', image=filename)
        w['7']['inputs'][f'ref_images.ref_image_{i}'] = [key, 0]
    if first_frame:
        w['17'] = node('LoadImage', image=first_frame)
        w['7']['inputs']['first_frame'] = ['17',0]
    if guide_frames is not None:
        # MiniMaxH3AddGuide anchors a single chronological IMAGE batch at frame zero.
        # Ordinary Ref2VA/one-frame workflows keep their original graph untouched.
        previous = ['17',0]
        for index, filename in enumerate(guide_frames[1:], 1):
            load_key = f'guide_load_{index}'
            batch_key = f'guide_batch_{index}'
            w[load_key] = node('LoadImage', image=filename)
            w[batch_key] = node('ImageBatch', image1=previous, image2=[load_key,0])
            previous = [batch_key,0]
        w['guide_last5'] = node('MiniMaxH3AddGuide', positive=['7',0], latent=['7',1],
                                vae=['3',0], image=previous, frame_idx=0)
        w['9']['inputs']['conditioning'] = ['guide_last5',0]
    model = ['1',0]
    if motion_lora:
        multiplier = {'normal': 0.6, 'high': 1.0, 'extreme': 1.3}[intensity]
        if director_mode == 'action':
            w['motion_combat'] = node('LoraLoaderModelOnly', model=model,
                lora_name=MOTION_LORAS['combat'], strength_model=round(0.65*multiplier,4))
            model = ['motion_combat',0]
        w['motion_repair'] = node('LoraLoaderModelOnly', model=model,
            lora_name=MOTION_LORAS['repair'], strength_model=round(0.35*multiplier,4))
        model = ['motion_repair',0]
    if kitchen_attention:
        w['attention_backend'] = node('ModelAttentionBackend', model=model,
                                      attention='comfy kitchen attention')
        model = ['attention_backend',0]
    if sparse_attention:
        w['sparse_attention'] = node('BlockSparseAttention', model=model,
            selection='sol-attn', **{'selection.tau': 1.3}, start_percent=0.2,
            end_percent=1.0, dense_blocks='', min_tokens=12288, extra_tokens=256,
            sink_conditioning='exact_kv_and_rows', verbose=True)
        model = ['sparse_attention',0]
    w['8']['inputs']['model'] = model
    return w



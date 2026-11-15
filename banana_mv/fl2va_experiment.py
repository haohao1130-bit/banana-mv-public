"""Isolated FL2VA Pruned INT8 benchmark for 5070. Never changes MV renderers."""
import argparse
import json
import math
import re
import time
from pathlib import Path
from banana_mv.core import FPS, align_frames, build_workflow
from banana_mv.comfy import comfy, queue_prompt, wait_prompt

PROFILES = {
    "base": ("minimax_h3_fl2va_pruned_int8_convrot.safetensors", 20),
    "turbo8": ("minimax_h3_fl2va_pruned_turbo_8step_v1.1_int8_convrot.safetensors", 8),
}

def build_fl2va_graph(*, first_frame, audio, prompt, seconds=10.0,
                      width=1280, height=736, seed=42, profile="turbo8",
                      last_frame=None, kitchen_attention=True):
    """I2VA/FL2VA keyframe conditioning, not multi-reference Ref2VA.

    Source audio is locked in latent AV via the T8 conditioning node.
    It must not also be registered as reference audio, since that would
    convert the T8 condition into a Hybrid / Ref2VA task.
    """
    if profile not in PROFILES:
        raise ValueError("Unknown FL2VA profile.")
    if not first_frame or not audio:
        raise ValueError("Provide current first frame and clipped audio filenames.")
    if not isinstance(seconds,(int,float)) or isinstance(seconds,bool) or not math.isfinite(seconds) or not 4<=seconds<=15:
        raise ValueError("FL2VA test duration must be between 4 and 15 seconds.")
    if not isinstance(width,int) or not isinstance(height,int) or min(width,height)<256 or width%32 or height%32:
        raise ValueError("FL2VA width and height must be multiples of 32.")
    if not isinstance(prompt,str) or not prompt.strip():
        raise ValueError("Provide current visual shot description.")
    if re.search(r'<(?:Audio|Video)\s+\d+>|<Picture\s+[2-9]\d*>',prompt,re.I):
        raise ValueError("FL2VA cannot accept Ref2VA audio or extra-picture tags.")
    if not isinstance(seed,int) or isinstance(seed,bool) or seed<0:
        raise ValueError("Seed must be a nonnegative integer.")
    model,steps=PROFILES[profile]
    frames=align_frames(math.ceil(seconds*FPS-1e-8))
    graph=build_workflow(
        first_frame, audio, width, height, frames, prompt, seed, steps=steps,
        acceleration=False, motion_lora=False,
        kitchen_attention=kitchen_attention, sparse_attention=False)
    graph["1"]["inputs"]["unet_name"]=model
    cond=graph["7"]["inputs"]
    for key in tuple(cond):
        if key.startswith("ref_images.") or key.startswith("ref_videos."):
            del cond[key]
    cond["first_frame"]=["5",0]
    cond["task_type"]="FL2VA" if last_frame else "I2VA"
    cond["add_source_as_reference"]=False
    cond["prompt_primary_audio_ordinal"]=0
    cond["strict_prompt_tags"]=True
    cond["audio_mode"]="lock_source"
    cond["audio_denoise_strength"]=0.0
    if last_frame:
        graph["last_frame_load"]={"class_type":"LoadImage","inputs":{"image":last_frame}}
        cond["last_frame"]=["last_frame_load",0]
    graph["16"]["inputs"]["filename_prefix"]=f"BananaMV_FL2VA_{profile}/test"
    if any(k.startswith("ref_images.") for k in cond) or cond["add_source_as_reference"]:
        raise RuntimeError("FL2VA experiment may not use Ref2VA media inputs.")
    return graph

def check_installed(comfy_cfg, graph):
    info=comfy(comfy_cfg,"/object_info")
    for node,field,name in (
        ("UNETLoader","unet_name",graph["1"]["inputs"]["unet_name"]),
        ("CLIPLoader","clip_name",graph["2"]["inputs"]["clip_name"]),
        ("VAELoader","vae_name",graph["3"]["inputs"]["vae_name"])):
        meta=info.get(node)
        if meta is None:
            raise RuntimeError(f"Missing ComfyUI node: {node}")
        fields=meta.get("input",{}).get("required",{})
        values=fields.get(field,[[]])
        options=values[0] if values and isinstance(values[0],list) else []
        if options and name not in options:
            raise FileNotFoundError(
                f"Model not installed in ComfyUI: {name}. No automatic download.")
    for node in ("MiniMaxH3AudioConditioningT8","MiniMaxH3SigmaShift",
                 "SamplerCustomAdvanced","VAEDecode","SaveVideo"):
        if node not in info:
            raise RuntimeError(f"ComfyUI missing required node: {node}")

def main(argv=None):
    p=argparse.ArgumentParser(description="Safe isolated RTX5070 FL2VA Pruned INT8 benchmark")
    p.add_argument("--first-frame",required=True,help="Image name in ComfyUI/input")
    p.add_argument("--last-frame",help="Optional final frame in ComfyUI/input")
    p.add_argument("--audio",required=True,help="Current clip WAV name in ComfyUI/input")
    p.add_argument("--prompt",default="An adult performer looks toward camera, smiles, turns around, then walks into the warm light. Camera tracks alongside.")
    p.add_argument("--prompt-file",type=Path)
    p.add_argument("--profile",choices=sorted(PROFILES),default="turbo8")
    p.add_argument("--seconds",type=float,default=10.0)
    p.add_argument("--width",type=int,default=1280)
    p.add_argument("--height",type=int,default=736)
    p.add_argument("--seed",type=int,default=42)
    p.add_argument("--comfy-url",default="http://127.0.0.1:8000")
    p.add_argument("--no-kitchen",action="store_true")
    p.add_argument("--workflow-out",type=Path)
    p.add_argument("--run",action="store_true",help="Queue real GPU rendering; default is dry-run")
    a=p.parse_args(argv)
    prompt=a.prompt_file.read_text(encoding="utf-8") if a.prompt_file else a.prompt
    graph=build_fl2va_graph(
        first_frame=a.first_frame,last_frame=a.last_frame,
        audio=a.audio,prompt=prompt,seconds=a.seconds,
        width=a.width,height=a.height,seed=a.seed,
        profile=a.profile,kitchen_attention=not a.no_kitchen)
    if a.workflow_out:
        a.workflow_out.parent.mkdir(parents=True,exist_ok=True)
        a.workflow_out.write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding="utf-8")
        print("Workflow saved:",a.workflow_out)
    print(f"FL2VA experiment: {a.profile}, {graph['12']['inputs']['steps']} steps, task {graph['7']['inputs']['task_type']}")
    print("Model:",graph["1"]["inputs"]["unet_name"])
    if not a.run:
        print("Dry-run only. No generation, no model download, no changes to existing BANANAMV.")
        return 0
    conf={"comfy_url":a.comfy_url}
    check_installed(conf,graph)
    started=time.perf_counter()
    prompt_id=queue_prompt(conf,graph)
    result=wait_prompt(conf,prompt_id,timeout=7200)
    elapsed=time.perf_counter()-started
    print(json.dumps({
        "profile":a.profile,"task":graph["7"]["inputs"]["task_type"],
        "model":graph["1"]["inputs"]["unet_name"],
        "seconds":a.seconds,"width":a.width,"height":a.height,
        "steps":graph["12"]["inputs"]["steps"],"seed":a.seed,
        "elapsed_wall_seconds":round(elapsed,3),"prompt_id":prompt_id,
        "video":result.get("outputs",{}).get("16",{})},
        ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

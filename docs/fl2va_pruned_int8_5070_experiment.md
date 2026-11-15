# 🍌 5070 FL2VA Pruned INT8｜獨立實驗分支

Branch: experiment/rtx5070-fl2va-pruned-int8

## Compatibility boundary

MiniMax FL2VA is first/last-frame conditioned, while Ref2VA accepts ordered
multi-image/audio/video references. The existing BANANAMV PRISM setup is Ref2VA
with multiple character pictures and locked original soundtrack.

**Never replace the production Ref2VA checkpoint with FL2VA inside that
existing graph.** The experimental branch instead adds an independent
ComfyUI I2VA/FL2VA benchmark builder. The original MV frontend, custom nodes,
auto-update desktop launcher, PRISM model, and 9B director are left intact.

## Profiles

Profile | ComfyUI diffusion model | Steps | Source
--- | --- | --- | ---
base | minimax_h3_fl2va_pruned_int8_convrot.safetensors | 20 | Comfy-Org/MiniMax-H3
turbo8 | minimax_h3_fl2va_pruned_turbo_8step_v1.1_int8_convrot.safetensors | 8 | Spectrallic/MiniMax-H3-LightX2V-int8-convrot

The turbo8 checkpoint is already merged with a full 8-step LightX2V adapter.
Do not apply another FL2V Turbo LoRA. The unmerged official base defaults
to 20 steps as a reference rather than unvalidated 8-step sampling.

Source files:
- https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models
- https://huggingface.co/Spectrallic/MiniMax-H3-LightX2V-int8-convrot

Download only your chosen checkpoint into the existing ComfyUI
models/diffusion_models directory. This experiment does not download,
delete, move, or overwrite any model. Expect a large file (around 20 GB).
Reuse the installed 32B NVFP4 text encoder, video VAE, audio VAE, and
MiniMaxH3AudioConditioningT8 custom node.

## Command (from the NEW experimental checkout root)

Provide a true opening-frame PNG and a 10-second audio WAV, already copied
into ComfyUI/input; this is not a two-reference-character shoot.

For a safe non-GPU API workflow export:

    python -m banana_mv.fl2va_experiment --first-frame first.png --audio song10s.wav --profile turbo8 --seconds 10 --workflow-out fl2va_test.json

For one actual GPU benchmark:

    python -m banana_mv.fl2va_experiment --first-frame first.png --audio song10s.wav --profile turbo8 --seconds 10 --run

Use --comfy-url if your ComfyUI is not on localhost port 8000.
Use --last-frame end.png for the full first+last-frame FL2VA task.
Without --last-frame, the task type is I2VA.
Use --profile base to run the unmerged pruned checkpoint (20 steps).
Use --no-kitchen only to test another attention backend.
The generated canvas defaults to 1280x736 (720p aligned) at 24 fps,
model frame count aligned to 17n+5, fixed seed 42.

The experiment uses audio_mode=lock_source but DOES NOT make audio a
Ref2VA reference token. Do not use Audio 1 or a second Picture tag in
the visual prompt. Multi-character Ref2VA performance and lip-sync
quality cannot be assumed equivalent.

## Benchmark honesty

- Compare time in seconds (elapsed_wall_seconds), GPU/RAM and visuals.
- The PRISM 8-step Ref2VA task is different from FL2VA 8-step I2VA.
- A faster FL2VA test does not establish a corresponding double-singer
  Ref2VA acceleration. The normal MV uses PRISM unchanged.
- The existing desktop one-click updater continues tracking the original
  experiment/rtx5070-480p-local branch. It does not switch automatically.
- No real local RTX 5070 generation has been run by this commit.

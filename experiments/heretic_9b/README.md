# BANANAMV RTX 5070 | Heretic 9B director A/B experiment

This experiment branches from banana-mv-public:experiment/rtx5070-480p-local. It changes **no** production backend, frontend, launcher, ComfyUI graph, or original weights. It is an optional research harness only.

## First gate: can Heretic read the model?

BANANAMV currently talks to a 9B model through ComfyUI TextGenerate and may use a specialized W4A8 or ComfyUI-only file layout. Heretic 2.x loads **Hugging Face Transformers-compatible model directories**; a ComfyUI .safetensors file by itself is NOT proof of compatibility. Before touching CUDA, identify the exact 9B architecture and original weights:

- A usable local HF model directory usually has config.json, tokenizer assets, and safetensors weight shards.
- If you only have a ComfyUI text-encoder W4A8 model, **stop here**. Do not rename files or force-load them.
- A 12 GB RTX 5070 may still run out of memory. bnb_4bit and CPU offload reduce memory needs, but don't guarantee success.
- Do not install Heretic into the existing Banana9B-cu130 or ComfyUI environment. Use a separate venv and model-output directory. Do not upload model weights, song files, or private data to any service.

## Phase A: measure the current director first

Store matched input and output records as UTF-8 JSONL; one object per line. Each input case contains id, required (terms expected in the generated shot), forbidden (unassigned characters/events), and expect_json (only if that route truly expects JSON). Each model response file contains id and output.

A tiny demonstration dataset lives under examples/. These are deliberately fictional examples, not actual model results.

From repo root:

    python experiments/heretic_9b/evaluate.py --cases experiments/heretic_9b/examples/cases.jsonl --baseline experiments/heretic_9b/examples/baseline.jsonl --candidate experiments/heretic_9b/examples/candidate.jsonl

After a real local 9B run, create baseline.jsonl and candidate.jsonl outside the repo (e.g. in %LOCALAPPDATA%/BananaHereticLab), using the same **current clip commission only** for both. Compare the same 20+ test cases and preserve raw generations. Judge shot quality manually; no heuristic substitutes for looking at the result.

## Phase B: optional Heretic 2.x tuning (only after compatibility is confirmed)

Install in a *separate* Python environment with a compatible CUDA PyTorch build, as described in the upstream Heretic README: https://github.com/p-e-w/heretic

    pip install -U heretic-llm

Heretic uses config.toml in its current working directory or HERETIC_CONFIG_FILE. The experiment has its own explicit config and small local prompt dataset. In PowerShell, from the dedicated environment:

    cd experiments\heretic_9b
    $env:HERETIC_CONFIG_FILE = (Resolve-Path .\config.banana_noslop.toml).Path
    heretic "D:\path\to\compatible\hf-original-9b-model"

This path is an illustrative placeholder, NOT the installed BANANAMV W4A8 model path. Never run against the only existing model copy. Review Heretic's save/export prompt and export to a NEW directory. No automatic upload is requested.

This config targets generic preamble / filler text and preserves some original-model behavior using KL divergence. It is **not** a JSON-validator, a singer-role trainer, or a guarantee of cinematic improvement. It intentionally does NOT use Heretic's default refusal-suppression recipe.

## Phase C: A/B acceptance gates

Compare original and modified outputs on exactly the same commissions, decoding settings, and source references. Inspect at least these dimensions:

1. Clear action, attention, and camera instructions, without empty opening/closing prose.
2. No future-scene leakage, surprise cast, repeated completed action, or singer-role swap.
3. JSON validity only for paths that actually require JSON; other H3 prompts are plain text.
4. Real-world performance, output quality, and GPU/CPU memory use.

The evaluation script reports text-based proxy metrics; it does not claim to validate motion continuity or filmmaking quality. Keep the original model as the default until a manual video-quality review agrees.

## Rollback

There is nothing to roll back at runtime: production is not wired to this branch. Switch back to experiment/rtx5070-480p-local and use the current 9B model exactly as before. Do not merge this experimental branch automatically.

Upstream: Heretic 2.x configs are not compatible with 1.x configs; check their current docs before running. This scaffold is prepared from the public 2.x config structure but has NOT been GPU-tested on the RTX 5070.

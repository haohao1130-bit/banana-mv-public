# BANANAMV Python Slot — RTX 5070 12 GB 本機 480p｜Stage 1

Base: `experiment/python-slot-director` (the completed 28-clip 4:32 MV experiment).
This branch is isolated from `main`, Classic Colab, VNext, and Fusion.

## Stage 1 scope
- Keep the exact Python-owned slot allocator / single-clip native 9B director / H3 first-last-frame pipeline.
- Local defaults: chain mode, 480p, 5-second slots; 10s/15s remain selectable with higher VRAM risk.
- 16:9 output 854x480 (generation uses 864x480 for 32-pixel alignment).
- No NVIDIA upscaling in this stage; that is a separate postproduction step for Stage 2.
- Reuse installed CU130 ComfyUI and existing 9B / H3 models. No model downloads.

## Windows isolated launcher
An accompanying downloadable launcher ZIP starts this branch at:
- repo: `%USERPROFILE%\banana-mv-5070`
- data: `%LOCALAPPDATA%\BananaMV5070`
- Banana web: `http://127.0.0.1:8193`
- shared ComfyUI: `http://127.0.0.1:8000`

It checks the existing CUDA 13.0 PyTorch environment and required ComfyUI node types, makes no Git resets or force merges, and does not stop existing GPU processes.
The launcher begins with `--lowvram` / `--preview-method none`; a separate optional CPU-VAE entrypoint can be used after manually stopping the ComfyUI instance it started.
If the existing ComfyUI is already running, the launcher reuses that process and does **not** alter its flags.
Windows-specific local assumptions are inherited from the user's previously working CU130 desktop layout.

## First validation on 5070 (not yet performed)
1. Start already-installed CU130 ComfyUI and the isolated Banana server, confirming `TextGenerate` and `MiniMaxH3AudioConditioningT8` are present.
2. Run one 480p 5s clip with the same models, 8 steps and chain mode; check GPU and system RAM usage.
3. Run two clips to test 5s boundary handoff and relative audio timing.
4. Only after that, test 10 seconds or a longer song, and finally consider an independent NVIDIA upscale stage.

**Limitations:** Static branch/UI/launcher inspection only; no actual RTX 5070 GPU execution in this environment. H3's total model weight footprint is much greater than 12 GB, so dynamic offloading/host RAM are essential and OOM is possible. 5s is a reasonable first experiment, not a guarantee of success.
## Windows desktop installer (V2)
Download the Windows desktop installer ZIP distributed with the 5070 package, extract it, and double-click `Install_Desktop_Shortcut.cmd` once. It copies persistent launchers into `%LOCALAPPDATA%\BananaMV-5070-CU130-Launcher` and creates desktop shortcuts for normal launch, optional CPU VAE, and explicit T8 repair. The normal shortcut opens the Banana UI at **http://127.0.0.1:8193** automatically. **8192 is Fusion Lab and must not be reused.**

Missing `MiniMaxH3AudioConditioningT8` is now a non-blocking launcher warning so that the Banana frontend can still open, but generation requires the node. The optional T8 repair helper clones only the custom-node source after explicit confirmation, never auto-downloads models or modifies Torch/CUDA. Restart existing ComfyUI manually after a repair; an instance started with `--disable-all-custom-nodes` will never load T8.


## Timecoded full-prompt parsing (5070-only fix)
The 5070 branch now recognizes Markdown scene headings such as `### 第一段｜00:00–00:10｜午夜開場` and routes them according to their **explicit song-time interval**, independent of whether H3 chunks are 5 or 10 seconds. Multiple story phases can share a technical chunk if a boundary crosses it. Cast, location, camera policy and generalized continuity statements remain in shared fixed setup, while ordinal-targeted rules (`第一段...`, `第四、第五段...`) and final-time instructions are sent only to their associated chapters. User-defined scenes remain ordered; later-scene actions are not supplied to earlier commissions.

An actual 44.5-second source song in 5-second chunks yields **9 clips: 0–5, 5–10, 10–15, 15–20, 20–25, 25–30, 30–35, 35–40, 40–44.5**, corresponding to five explicitly defined 10/10/10/10/4.5-second story chapters. The legacy numbered-act parser is untouched for scripts without explicit timestamped Markdown scenes.

### Testing it on Windows
1. Stop the **Banana 5070 backend** window, then double-click the existing 5070 desktop shortcut. If the checkout is clean, its launcher fast-forwards this branch automatically; ComfyUI and model files are reused.
2. Open `http://127.0.0.1:8193` and check `git -C "$env:USERPROFILE\banana-mv-5070" log -1 --oneline`.
3. Create a **fresh test project** and choose 5-second clips, 720p if already validated on that machine.
4. Inspect the new `director_plan.json`: every clip must contain only its applicable timecoded story chapter and no standalone Markdown metadata as actions.

Saved projects retain their original `director_plan.json` and are **not silently rewritten** on update; to verify the parser fix, use a fresh test project.

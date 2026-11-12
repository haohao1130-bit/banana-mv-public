# Colab Python Slot — 5070 backport handoff (2026-11-12)

## Branch policy
- Desktop development/test: `experiment/rtx5070-480p-local`
- Public Colab experimental intake: `experiment/python-slot-director`
- Public Classic `main` remains untouched until Colab GPU verification.
- Same H3 / 9B pipeline, with environment-specific launch and defaults.

## Included in the Colab experimental branch
- Python timecoded Markdown chapters: `banana_mv/timed_slots.py` plus `python_slots.py` integration.
- Python-owned current actor state, event continuity, chapter scoping and per-property wardrobe state priority (`python_slots.py`, `shoot_plan.py`).
- `chain5` as a third mode alongside independent/chain: five consecutive tail images passed to `MiniMaxH3AddGuide` at frame zero; 5 overlapping output frames are trimmed, and the original audio timeline is retained (`core.py`, `server.py`, `takes.py`).
- Resumption and retake route via the same continuation treatment, with five-frame preflight and reference limit (8 images).
- New Python, core, server, shoot, and browser tests copied/adjusted for the shared implementation.

## Intentionally NOT copied
- RTX 5070 desktop supervisor, restart HTTP endpoints, Windows launchers.
- Local 480p/5-second defaults. Colab Notebook UI still defaults to 720p and 10-second clips and offers 10/15 seconds.
- The original Colab notebook name, pinned branch, Drive directory, ComfyUI pinned install, or Demucs SSL mirror fix.
- No public `main` deployment.

## Compatibility evidence
- Verified `MiniMaxH3AddGuide` is defined at the exact ComfyUI revision pinned by `tools/colab_runtime.py` (`56f179f6c50dad0c4c860ae4da427415c8e86415`).
- Python imports, server/workflow/retake wiring, reference limits, Colab defaults, and notebook branch pin were inspected after updating.
- Unit test files were updated, but **unit tests were not executed in this connector environment**. No Colab GPU generation was attempted. Do not describe this backport as GPU-verified.

## Recommended validation sequence
1. Fresh Colab runtime: open `BANANAMV_CLASSIC_PYTHON_SLOT_EXPERIMENT.ipynb`. Confirm clone branch `experiment/python-slot-director` and installed pinned ComfyUI/H3 nodes.
2. Run `python -m unittest discover -s tests` and `node tests/check_ui.cjs` in the cloned project.
3. Use a fresh short test project at 480p (for cost), test independent and chain modes before chain5.
4. On chain5 with two clips, verify workflow contains `MiniMaxH3AddGuide`, five guide PNGs, five-frame overlap trimming, unchanged total output duration, source audio continuity, and retake/resume.
5. Only promote to `main` after a satisfactory GPU run and no regression of original 10/15-second modes.

## Known constraint
A currently saved `director_plan.json` is not silently rewritten to the new Python allocation. Create a new project to test updated chapter interpretation.

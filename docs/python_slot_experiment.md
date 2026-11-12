# Classic Python Slot experiment (isolated branch)

Branch: `experiment/python-slot-director` in `haohao1130-bit/banana-mv-public`.

**Do not merge to main without a real Colab/GPU video test.** The stable Classic notebooks are unchanged. Use `BANANAMV_CLASSIC_PYTHON_SLOT_EXPERIMENT.ipynb`.

## What changed

- New jobs on this branch alone use `director_schema=6`; old saved jobs preserve their own schema and resume path.
- Python uses decoded audio duration to cut precise time slots, and writes a deterministic `director_plan.json` with one local commission per slot.
- Chapter headings (`第一幕｜...`, `終幕｜...`, `Act N:`) guide deterministic ordered allocation. A technical final tail no longer introduces a new ending.
- No whole-song 9B allocation call occurs in schema 6. The existing native H3 writer gets one local commission plus invariant character setup, SRT and local audio evidence, then writes that clip only.
- The source official H3 filmmaking guide, ref bindings, and per-clip camera decisions remain the Classic pipeline.

## Launch

Open [experiment Colab](https://colab.research.google.com/github/haohao1130-bit/banana-mv-public/blob/experiment/python-slot-director/BANANAMV_CLASSIC_PYTHON_SLOT_EXPERIMENT.ipynb).

Use a fresh GPU runtime and run ①②③. The first cell checks out the experiment branch explicitly. The third cell uses `MyDrive/BananaMVClassicPythonSlot` instead of stable `MyDrive/BananaMV`.

Use a 30–60 second audio excerpt first. Select plan review, inspect each time slot and then approve first-clip filming. Test the entire 28-clip song only after checking the short test. Keep `status.json`, `director_plan.json`, `00_prompt_v1.txt`, `00_workflow_v1.json` for diagnosis.

## Limitations

- Python can preserve ordered explicit story beats, but does not understand dramatic meaning from loudness or fabricate a full creative story in advance.
- Sparse user cues may yield anticipation slots that need clip-local creative expansion; this is an experiment and not guaranteed to match detailed timecoded direction.
- The previous ending contracts and SRT/audio guidance survive, but manually review exact required story timestamps.
- Do not launch Classic and experiment on the same runtime port. Use fresh Colab runtimes.
- Tests mock 9B/H3/ComfyUI. No CUDA or real Colab GPU video quality validation has been performed.

## Rollback

The stable Classic notebook remains [here](https://colab.research.google.com/github/haohao1130-bit/banana-mv-public/blob/main/BANANAMV_CLASSIC_PUBLIC.ipynb). Do not mix the two Drive data folders.

Regression tests: `tests/test_python_slots.py`; notebook builder: `tools/build_python_slot_notebook.py`.

# Classic MV on the existing RTX 5070 / CU130 environment

This edition starts from the Nov 8 `4155964` classic snapshot associated by date
with successful job `e27ca57a476d`. That job did not record its runtime SHA.
The expressive per-clip director and full official guide remain intact. The
small isolation change separates upstream STORY OUTCOME from shared identities
and scene duties. Internal cuts inside a numbered Shot remain allowed. There
is no new semantic reviewer or strict camera-timing gate.

The launcher reuses working CU130 ComfyUI on port 8000, or starts your existing
ComfyUI source if the API is unavailable. It does not launch a second ComfyUI
when the API already responds. Classic's backend now prefers the same Python
interpreter as the working local VNext launcher:
`%USERPROFILE%\Documents\ComfyUI\.venv\Scripts\python.exe` when it exists.
Otherwise it falls back to `%LOCALAPPDATA%\Banana9B-cu130\Scripts\python.exe`.
Use `-PythonPath` to select a custom known-working interpreter. This does not
install or upgrade Python, Torch, CUDA, ComfyUI, or model weights.

Clone the classic repo into a separate folder, leaving VNext and its outputs:

```powershell
git clone --branch main https://github.com/haohao1130-bit/banana-mv-public.git "$env:USERPROFILE\banana-mv-classic"
```

Create the desktop shortcut:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\banana-mv-classic\tools\create_classic_shortcut.ps1"
```

Double-click `Banana MV Classic CU130`. It updates the current branch with
`git pull --ff-only` and starts Classic at http://127.0.0.1:8191. Keep its
console open. The console prints repo path, branch, commit, data path and URL.
If an update fails, it stops and preserves files rather than resetting changes.

New Classic data is stored separately at `%LOCALAPPDATA%\BananaMVClassic`.
Existing VNext jobs are not migrated, overwritten, or removed. The launcher
copies existing rewriter settings only on the first Classic config creation.
It reuses the full guide from VNext when available; otherwise downloads the
official complete reference guide. The guide is not shortened.

For the first test choose **prepare recipe / plan review**, 480p, 10 seconds
per interval, the same images/audio/CUE, and English review to compare timing
without translation. If testing the old successful case, note its original
auto/extreme/dynamic-cuts settings; do not change these halfway through an A/B.

Video rendering is a separate acceptance step. The current local ComfyUI has
not yet exposed `MiniMaxH3AudioConditioningT8`; installing official H3 weights
alone does not make Banana source-audio rendering ready. This launcher does
not install that extension or submit a render. Successful recipe generation
does not claim successful RTX 5070 H3 video generation.

To compare existing VNext, its server can remain at 8190; do not submit
concurrent GPU jobs from both UIs. The current Tailscale proxy for port 8190
continues to point to VNext unless explicitly changed.

For troubleshooting audio upload, Classic prints the selected Python and ffprobe
paths. ffprobe JSON uses explicit UTF-8 decoding (as in local VNext); if its
capture is empty or invalid the backend reports an actionable media-probe error
instead of a generic JSON NoneType failure. If the backend upload route fails,
it writes the local traceback to `%LOCALAPPDATA%\\BananaMVClassic\\upload_error.log`
for inspection; this log is never served by the web interface.

If your VNext launcher uses a custom Python, launch Classic with the same path:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\banana-mv-classic\tools\start_classic_local.ps1" -PythonPath "C:\\path\\to\\working\\python.exe"
```

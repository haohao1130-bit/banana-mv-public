param(
    [string]$ComfySource,
    [string]$ComfyBase,
    [string]$ComfyPython
)
$ErrorActionPreference = 'Stop'
$settingsPath = 'F:\AI\BANANA_FILM_5070_STUDIO\Launcher\settings.json'
if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    if (!$ComfySource) { $ComfySource = $settings.ComfySource }
    if (!$ComfyBase) { $ComfyBase = $settings.ComfyBase }
}
if (!$ComfySource) { $ComfySource = Join-Path $env:LOCALAPPDATA 'Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI' }
if (!$ComfyBase) { $ComfyBase = Join-Path $env:USERPROFILE 'Documents\ComfyUI' }
if (!$ComfyPython) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Banana9B-cu130\Scripts\python.exe')
        (Join-Path $ComfyBase '.venv\Scripts\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            & $candidate -c "import torch; assert torch.cuda.is_available() and str(torch.version.cuda).startswith('13')"
            if ($LASTEXITCODE -eq 0) { $ComfyPython = $candidate; break }
        }
    }
}
if (!$ComfyPython) { throw 'ComfyUI CUDA 13 Python not found. Specify -ComfyPython.' }
& $ComfyPython (Join-Path $PSScriptRoot 'install_face_refine.py') --comfy-source $ComfySource --comfy-base $ComfyBase
if ($LASTEXITCODE -ne 0) { throw "FaceRefine installation failed (exit $LASTEXITCODE)." }

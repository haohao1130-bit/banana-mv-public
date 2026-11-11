param(
    [string]$ComfyUrl = 'http://127.0.0.1:8000',
    [int]$Port = 8191,
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'BananaMVClassic'),
    [string]$PythonPath = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$comfyRoot = Join-Path $env:USERPROFILE 'Documents\ComfyUI'
$vnextPython = Join-Path $comfyRoot '.venv\Scripts\python.exe'
$cu130Python = Join-Path $env:LOCALAPPDATA 'Banana9B-cu130\Scripts\python.exe'
if (-not $PythonPath) {
    if (Test-Path -LiteralPath $vnextPython) { $PythonPath = $vnextPython }
    else { $PythonPath = $cu130Python }
}
$python = $PythonPath
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python not found: $python. Use -PythonPath with the interpreter from your working VNext launch."
}
& $python -c 'import PIL, numpy'
if ($LASTEXITCODE -ne 0) { throw "Python lacks Pillow or numpy: $python. Select the same working Python as VNext." }
foreach ($binary in @('ffmpeg','ffprobe')) {
    if (-not (Get-Command $binary -ErrorAction SilentlyContinue)) { throw "$binary is missing from PATH." }
}
$nodes = $null
try { $nodes = Invoke-RestMethod -Uri "$ComfyUrl/object_info" -TimeoutSec 3 }
catch {
    $source = Join-Path $env:LOCALAPPDATA 'Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI'
    $main = Join-Path $source 'main.py'
    if (-not (Test-Path -LiteralPath $main)) { throw 'ComfyUI source not found. Start your existing CU130 ComfyUI first.' }
    Write-Host 'Starting existing ComfyUI with CU130. Keep its console open.'
    Start-Process -FilePath $python -WorkingDirectory $source -ArgumentList @('-u', ('"' + $main + '"'), '--base-directory', ('"' + $comfyRoot + '"'), '--listen', '127.0.0.1', '--port', '8000') | Out-Null
    $deadline = (Get-Date).AddMinutes(2)
    while ($null -eq $nodes -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        try { $nodes = Invoke-RestMethod -Uri "$ComfyUrl/object_info" -TimeoutSec 3 }
        catch { Write-Host 'Waiting for CU130 ComfyUI...' }
    }
}
if ($null -eq $nodes.TextGenerate) { throw 'Start your working CU130 ComfyUI on port 8000 first.' }
$guideDir = Join-Path $projectRoot 'guides'
$guide = Join-Path $guideDir 'VIDEO_PROMPT_WRITING_GUIDE_ref_en.md'
New-Item -ItemType Directory -Force -Path $guideDir | Out-Null
if (-not (Test-Path -LiteralPath $guide)) {
    $savedGuide = Join-Path $env:LOCALAPPDATA 'BananaMVVNext\guides\VIDEO_PROMPT_WRITING_GUIDE_ref_en.md'
    if (Test-Path -LiteralPath $savedGuide) { Copy-Item -LiteralPath $savedGuide -Destination $guide }
    else { Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/MiniMaxAI/MiniMax-H3/resolve/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md' -OutFile $guide }
}
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$configPath = Join-Path $DataRoot 'config.json'
$config = [pscustomobject]@{}
if (Test-Path -LiteralPath $configPath) { $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json }
elseif (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'BananaMVVNext\config.json')) {
    $previous = Get-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'BananaMVVNext\config.json') -Raw | ConvertFrom-Json
    if ($null -ne $previous.rewriter) { $config | Add-Member -NotePropertyName 'rewriter' -NotePropertyValue $previous.rewriter }
}
$config | Add-Member -NotePropertyName 'comfy_url' -NotePropertyValue $ComfyUrl -Force
$config | Add-Member -NotePropertyName 'comfy_input_dir' -NotePropertyValue (Join-Path $comfyRoot 'input') -Force
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 20), $utf8)
$env:BANANA_DATA = $DataRoot
$env:BANANA_PORT = [string]$Port
Write-Host 'BANANA MV CLASSIC - CU130 - KEEP OPEN'
Write-Host "Repository: $projectRoot"
& git -C $projectRoot branch --show-current
& git -C $projectRoot log -1 --oneline
Write-Host "Data: $DataRoot"
Write-Host "Python: $python"
Write-Host "ffprobe: $((Get-Command ffprobe).Source)"
Write-Host "ComfyUI: $ComfyUrl"
Write-Host "Classic MV: http://127.0.0.1:$Port"
Write-Host 'Prepare recipe first. Video rendering needs the matching H3 models and Banana audio node.'
Push-Location $projectRoot
try { & $python -u -m banana_mv.server }
finally { Pop-Location }

$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'Banana MV Classic CU130.lnk'))
$shortcut.TargetPath = Join-Path $PSScriptRoot 'start_classic_local.cmd'
$shortcut.WorkingDirectory = Split-Path -Parent $PSScriptRoot
$shortcut.Description = 'Classic Banana MV, current branch auto-update, existing CU130 ComfyUI'
$shortcut.Save()
Write-Host 'Created Banana MV Classic CU130 desktop shortcut. The launcher reuses or starts CU130 ComfyUI.'

@echo off
setlocal
for %%I in ("%~dp0..") do set "CLASSIC_REPO=%%~fI"
git -C "%CLASSIC_REPO%" pull --ff-only
if errorlevel 1 goto failed
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_classic_local.ps1"
if errorlevel 1 goto failed
exit /b 0
:failed
echo Classic MV did not start. Read the error above. Existing data was kept.
pause
exit /b 1

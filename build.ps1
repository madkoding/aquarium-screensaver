# Builds Aquarium.scr (a PyInstaller one-file exe renamed to .scr).
# Needs: pip install -r requirements.txt pyinstaller
Set-Location $PSScriptRoot
python -m PyInstaller --noconfirm --onefile --noconsole --name Aquarium `
    --icon icon.ico --version-file version_info.txt `
    --hidden-import glcontext --collect-submodules moderngl `
    aquarium_saver.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
Copy-Item dist\Aquarium.exe Aquarium.scr -Force
Write-Host "Done: $PSScriptRoot\Aquarium.scr"
Write-Host "Install: right-click Aquarium.scr > Install"

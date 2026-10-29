# Builds dist\PlainProcessViewer.exe: one file with Python and everything the app needs inside.
# Needs the .venv from the README plus PyInstaller:  uv pip install --python .venv\Scripts\python.exe pyinstaller
# win32ui and pywin (pywin32's MFC parts) are left out: the app doesn't use them, and they need MFC, which plain Windows lacks.
$root = $PSScriptRoot
$app = Join-Path $root "app"

# Refresh the licences of everything packed in, so THIRD-PARTY-NOTICES.txt matches this build.
& (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "packaging\notices.py")
if ($LASTEXITCODE -ne 0) { throw "Couldn't write THIRD-PARTY-NOTICES.txt." }

& (Join-Path $root ".venv\Scripts\pyinstaller.exe") `
    --noconfirm --clean --onefile --windowed `
    --name PlainProcessViewer `
    --icon (Join-Path $app "static\app.ico") `
    --version-file (Join-Path $root "packaging\version.txt") `
    --paths $app `
    --add-data "$(Join-Path $app 'static');static" `
    --add-data "$(Join-Path $app 'data');data" `
    --add-data "$(Join-Path $app 'enrich.ps1');." `
    --exclude-module tkinter `
    --exclude-module win32ui --exclude-module pywin `
    --distpath (Join-Path $root "dist") `
    --workpath (Join-Path $root "build") `
    --specpath (Join-Path $root "build") `
    (Join-Path $root "main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$exe = Get-Item (Join-Path $root "dist\PlainProcessViewer.exe")
"Built $($exe.FullName) ($([math]::Round($exe.Length / 1MB, 1)) MB)"

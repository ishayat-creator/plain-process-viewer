@echo off
rem Opens Plain Process Viewer in its own window, without a console.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"

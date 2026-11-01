@echo off
setlocal
pushd "%~dp0" || exit /b 1

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo The project's Python environment was not found.
    echo Run these commands in this folder to set it up:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    popd
    exit /b 1
)

start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app_gui.py"
popd
endlocal

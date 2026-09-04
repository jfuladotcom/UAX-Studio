@echo off
setlocal
cd /d "%~dp0"
set "VENV_DIR=.venv"
if exist "venv\Scripts\python.exe" set "VENV_DIR=venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
  py -m venv "%VENV_DIR%"
)
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install -r requirements.txt
python run.py

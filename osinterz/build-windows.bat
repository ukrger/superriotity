@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller==6.16.0
if errorlevel 1 goto fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name "osinterz-by-abjectov" --collect-submodules phonenumbers app.py
if errorlevel 1 goto fail
echo Ready: dist\osinterz-by-abjectov.exe
pause
exit /b 0
:fail
echo Build failed. See the error above. Install Python 3.12 x64 from python.org.
pause
exit /b 1

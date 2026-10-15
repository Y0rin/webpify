@echo off
rem Builds dist\WebPify.exe (a single file that runs without Python installed).
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -m pip install --quiet -r requirements.txt pyinstaller || goto :error
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name WebPify ^
    --icon assets\logo.ico ^
    --add-data "assets;assets" ^
    --collect-data sv_ttk ^
    converter_gui.pyw || goto :error

echo.
echo Done: dist\WebPify.exe
pause
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1

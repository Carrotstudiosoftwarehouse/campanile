@echo off
rem DEVELOPED BY CARROTSTUDIO software house
rem Double click on Windows to start Campanile on this computer.
cd /d "%~dp0"
rem Commands come from Windows only, never from this folder: a stick can hold anything.
set "NoDefaultCurrentDirectoryInExePath=1"

rem "python" may be the Microsoft Store's placeholder, which only says Python is missing:
rem a candidate counts only if it really runs Python 3.9 or newer.
set "PYTHON="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && set "PYTHON=python"
if not defined PYTHON goto no_python

%PYTHON% campanile\launch.py
echo.
echo Campanile spento / Campanile is off.
pause
exit /b 0

:no_python
echo.
if exist "%~dp0tools\python\" goto python_here
echo  Serve Python 3, gratuito: https://www.python.org/downloads/
echo  Durante l'installazione spunta "Add python.exe to PATH", poi fai di nuovo doppio clic qui.
echo.
echo  Python 3 is needed, free: https://www.python.org/downloads/
echo  While installing, tick "Add python.exe to PATH", then double-click here again.
echo.
pause
exit /b 1

:python_here
rem A copy from a USB stick brings Python's official installers: no internet needed.
set "ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"
echo  Serve Python 3: e' gia' qui, nella cartella tools\python.
echo  Fai doppio clic su python-...-%ARCH%.exe, spunta "Add python.exe to PATH",
echo  poi fai di nuovo doppio clic qui.
echo.
echo  Python 3 is needed: it's right here, in the folder tools\python.
echo  Double-click python-...-%ARCH%.exe, tick "Add python.exe to PATH",
echo  then double-click here again.
echo.
start "" "%~dp0tools\python"
pause
exit /b 1

@echo off
setlocal

where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0start.py" %*
exit /b %errorlevel%

:use_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python "%~dp0start.py" %*
exit /b %errorlevel%

:no_python
echo Python 3.10 or newer is required. 1>&2
exit /b 1

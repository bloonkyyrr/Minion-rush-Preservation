@echo off
rem Start the Minion Rush traffic catcher. Extra arguments go to mitmdump.
setlocal
pushd "%~dp0"
python -m catcher.cli run %*
set EXITCODE=%ERRORLEVEL%
popd
exit /b %EXITCODE%

@echo off
setlocal
cd /d "%~dp0"
python scripts\check_release_clean.py %*

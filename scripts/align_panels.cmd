@echo off
REM Quick panel alignment utility
REM Usage: align_panels.cmd [--desktop DESKTOP] [--dry-run] [--configure]

cd /d "%~dp0\.."
python scripts\align_panels.py %*

@echo off
setlocal
set "REPO_ROOT=%~dp0"
set "VENV_PY=%REPO_ROOT%.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
	"%VENV_PY%" -m automation.cli.master %*
) else (
	python -m automation.cli.master %*
)
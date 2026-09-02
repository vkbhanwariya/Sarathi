@echo off
cd /d "%~dp0"

REM 1. Prefer 'uv run' if uv is available
where uv >nul 2>&1
if %ERRORLEVEL% equ 0 (
    uv run python -m sarathi %*
    exit /b %ERRORLEVEL%
)

REM 2. Fallback to local virtualenv python
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m sarathi %*
    exit /b %ERRORLEVEL%
)

REM 3. Fallback to system python
python -m sarathi %*
exit /b %ERRORLEVEL%

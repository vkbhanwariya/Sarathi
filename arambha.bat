@echo off
setlocal
cd /d "%~dp0"

:: 1. Prefer 'uv run' if uv is available
where uv >nul 2>&1
if %ERRORLEVEL% equ 0 (
    uv run python -m sarathi %*
    exit /b %ERRORLEVEL%
)

:: 2. Fallback to local virtualenv python
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m sarathi %*
    exit /b %ERRORLEVEL%
)

:: 3. Fallback to system python
python -m sarathi %*
exit /b %ERRORLEVEL%

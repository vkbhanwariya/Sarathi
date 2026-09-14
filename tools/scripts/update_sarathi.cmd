@echo off
setlocal
cd /d "%~dp0"

REM Prefer pwsh (PowerShell 7) if available, otherwise use Windows PowerShell
where pwsh >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PS_EXE=pwsh"
) else (
    set "PS_EXE=powershell"
)

"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_sarathi.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if %EXIT_CODE% neq 0 (
    echo [ERROR] Process finished with exit code %EXIT_CODE%.
) else (
    echo [DONE] Process completed successfully.
)
echo Press any key to close this window . . .
pause >nul
exit /b %EXIT_CODE%

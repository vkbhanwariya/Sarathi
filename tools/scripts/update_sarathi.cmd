@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM Prefer pwsh (PowerShell 7) if available, otherwise use Windows PowerShell
where pwsh >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PS_EXE=pwsh"
) else (
    set "PS_EXE=powershell"
)

REM If arguments were passed directly (e.g. from CI or scripts), run headless pass-through
if not "%~1"=="" (
    "%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_sarathi.ps1" %*
    exit /b %ERRORLEVEL%
)

:MENU
cls
echo ========================================================================
echo                   Sarathi Maintenance ^& Setup Console
echo ========================================================================
echo.
echo   [1] Update / Install Sarathi Dependencies
echo       Synchronize uv virtual environment, verify capability extras, and check PyPI.
echo.
echo   [2] Update / Setup OCR Models
echo       Download and verify RapidOCR PP-OCRv5 Devanagari/English ONNX models.
echo.
echo   [3] Update / Setup Translation Models
echo       Download and verify CTranslate2 Neural Translation models (Hindi ^<-^> English).
echo.
echo   [4] Full Setup (Run All: 1, 2, and 3)
echo       Sequential complete environment and model assets provisioning.
echo.
echo   [5] Quick Verification Audit (100%% Offline)
echo       Fast integrity verification for OCR, Translation, and SIL font maps.
echo.
echo   [6] Update All External Assets
echo       Download/update SIL maps, RapidOCR models, and translation assets from upstream.
echo.
echo   [7] Exit
echo.
echo ========================================================================
set /p "CHOICE=Select an option [1-7] (Default: 1): "
if "%CHOICE%"=="" set "CHOICE=1"

if "%CHOICE%"=="1" goto RUN_DEPS
if "%CHOICE%"=="2" goto RUN_OCR
if "%CHOICE%"=="3" goto RUN_TRANS
if "%CHOICE%"=="4" goto RUN_ALL
if "%CHOICE%"=="5" goto RUN_VERIFY
if "%CHOICE%"=="6" goto RUN_ASSETS
if "%CHOICE%"=="7" goto EXIT_SCRIPT

echo.
echo [!] Invalid option selected. Please try again.
timeout /t 2 >nul
goto MENU

:RUN_DEPS
echo.
echo [*] Running Sarathi dependency synchronization...
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_sarathi.ps1"
goto AFTER_OP

:RUN_OCR
echo.
echo [*] Running RapidOCR model provisioning...
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-OCRModels.ps1"
goto AFTER_OP

:RUN_TRANS
echo.
echo ------------------------------------------------------------------------
echo Choose Translation Engine Variant:
echo   [1] OPUS-MT (Marian INT8, ~160MB) - Fast, lightweight, recommended
echo   [2] IndicTrans2 (AI4Bharat 200M, ~1.7GB) - High-fidelity Indic NMT
echo   [3] Both (Complete offline suite)
echo ------------------------------------------------------------------------
set /p "TRANS_CHOICE=Select variant [1-3] (Default: 1): "
if "%TRANS_CHOICE%"=="" set "TRANS_CHOICE=1"

set "ENGINE_ARG=opus_mt"
if "%TRANS_CHOICE%"=="2" set "ENGINE_ARG=indictrans2"
if "%TRANS_CHOICE%"=="3" set "ENGINE_ARG=all"

set "TOKEN_PARAM="
if not "%ENGINE_ARG%"=="opus_mt" (
    if "%HF_TOKEN%"=="" if "%HUGGING_FACE_HUB_TOKEN%"=="" (
        echo.
        echo [Optional] Hugging Face token is recommended for large IndicTrans2 downloads.
        set /p "USER_HF_TOKEN=Enter Hugging Face Token (press Enter to skip): "
        if not "!USER_HF_TOKEN!"=="" set "TOKEN_PARAM=-HfToken !USER_HF_TOKEN!"
    )
)

echo.
echo [*] Running Translation model provisioning (Engine: %ENGINE_ARG%)...
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-TranslationModels.ps1" -Engine %ENGINE_ARG% %TOKEN_PARAM%
goto AFTER_OP

:RUN_ALL
echo.
echo ========================================================================
echo [*] Step 1/3: Synchronizing Dependencies...
echo ========================================================================
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_sarathi.ps1" -CheckOnly
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Dependencies check failed.
    goto AFTER_OP
)

echo.
echo ========================================================================
echo [*] Step 2/3: Provisioning OCR Models...
echo ========================================================================
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-OCRModels.ps1"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] OCR models provisioning failed.
    goto AFTER_OP
)

echo.
echo ========================================================================
echo [*] Step 3/3: Provisioning Translation Models (OPUS-MT)...
echo ========================================================================
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-TranslationModels.ps1" -Engine opus_mt
goto AFTER_OP

:RUN_VERIFY
echo.
echo ========================================================================
echo [*] Verifying All External Assets Integrity (100%% Offline)...
echo ========================================================================
uv run --project "%~dp0..\.." python "%~dp0..\update_assets.py" --check
goto AFTER_OP

:RUN_ASSETS
echo.
echo ========================================================================
echo [*] Updating All Declared External Assets from Upstream...
echo ========================================================================
uv run --project "%~dp0..\.." python "%~dp0..\update_assets.py" --all
goto AFTER_OP

:AFTER_OP
set "LAST_ERR=%ERRORLEVEL%"
echo.
if %LAST_ERR% equ 0 (
    echo [OK] Selected operation completed successfully.
) else (
    echo [ERROR] Selected operation exited with code %LAST_ERR%.
)
echo.
echo Press [Enter] to return to the menu, or [Q] to quit...
set /p "AGAIN="
if /i "%AGAIN%"=="Q" goto EXIT_SCRIPT
goto MENU

:EXIT_SCRIPT
echo Exiting Sarathi Maintenance Console.
exit /b 0

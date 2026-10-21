@echo off
setlocal
set "PROJ_ROOT=%~dp0"
cd /d "%PROJ_ROOT%"

echo ===================================================
echo   Fund Manager Launcher (Windows / Python Env)
echo ===================================================
echo.

:: 0. Force uv to use local system Python
set "UV_PYTHON_PREFERENCE=only-system"

:: 1. Auto-detect existing uv in standard locations
where uv >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    if exist "%LOCALAPPDATA%\bin\uv.exe" set "PATH=%LOCALAPPDATA%\bin;%PATH%"
    if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    if exist "%APPDATA%\Python\Scripts\uv.exe" set "PATH=%APPDATA%\Python\Scripts;%PATH%"
)

:: 2. Bootstrap uv via pip if missing
where uv >nul 2>&1
if %errorlevel% neq 0 (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python is not installed or not in PATH.
        echo Please install Python and ensure it is added to your environment variables.
        echo.
        pause
        exit /b 1
    )
    echo [INFO] 'uv' package manager not found. Bootstrapping via pip...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install uv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install 'uv'.
        echo.
        pause
        exit /b 1
    )
    echo [INFO] 'uv' installed successfully.
)

:: 3. Auto-detect Python entry point
set "ENTRY_POINT="
if exist "%PROJ_ROOT%app.py" set "ENTRY_POINT=app.py"
if not defined ENTRY_POINT if exist "%PROJ_ROOT%main.py" set "ENTRY_POINT=main.py"
if not defined ENTRY_POINT if exist "%PROJ_ROOT%cli.py" set "ENTRY_POINT=cli.py"

if not defined ENTRY_POINT (
    echo [ERROR] Python entry point not found.
    pause
    exit /b 1
)

echo [INFO] Entry point found: %ENTRY_POINT%
echo [INFO] Working directory: %PROJ_ROOT%

:: 4. Auto-create .venv and sync package dependencies
if not exist ".venv" (
    echo [INFO] Creating virtual environment...
    uv venv --python python
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment .venv.
        pause
        exit /b %errorlevel%
    )
)

if exist "pyproject.toml" (
    echo [INFO] Syncing dependencies...
    uv sync
    if %errorlevel% neq 0 (
        echo [ERROR] Dependency sync failed.
        pause
        exit /b %errorlevel%
    )
)

:: 5. Launch Application
echo.
echo [INFO] Launching %ENTRY_POINT% ...
echo.

findstr /i "streamlit" pyproject.toml >nul 2>&1
if %errorlevel% equ 0 (
    uv run streamlit run "%ENTRY_POINT%" --server.headless false
) else (
    uv run python "%ENTRY_POINT%"
)

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Application encountered an error or stopped.
)

echo.
pause

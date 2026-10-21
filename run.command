#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==================================================="
echo "  Fund Manager Launcher (Mac/Linux / Python Env)"
echo "==================================================="
echo ""

export UV_PYTHON_PREFERENCE=only-system

if ! command -v uv &> /dev/null; then
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
fi

if ! command -v uv &> /dev/null; then
    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    fi

    if [ -z "$PYTHON_CMD" ]; then
        echo "[ERROR] Python is not installed or not in PATH."
        read -p "Press [Enter] key to exit..."
        exit 1
    fi

    echo "[INFO] 'uv' package manager not found. Bootstrapping via pip..."
    $PYTHON_CMD -m pip install --upgrade pip >/dev/null 2>&1
    $PYTHON_CMD -m pip install uv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install 'uv'."
        read -p "Press [Enter] key to exit..."
        exit 1
    fi
    echo "[INFO] 'uv' installed successfully."
fi

ENTRY_POINT=""
for file in app.py main.py cli.py; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        ENTRY_POINT="$file"
        break
    fi
done

if [ -z "$ENTRY_POINT" ]; then
    echo "[ERROR] Python entry point not found."
    read -p "Press [Enter] key to exit..."
    exit 1
fi

echo "[INFO] Entry point found: $ENTRY_POINT"
echo "[INFO] Working directory: $SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment..."
    uv venv --python python
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment .venv."
        read -p "Press [Enter] key to exit..."
        exit 1
    fi
fi

if [ -f "pyproject.toml" ]; then
    echo "[INFO] Syncing dependencies..."
    uv sync
    if [ $? -ne 0 ]; then
        echo "[ERROR] Dependency sync failed."
        read -p "Press [Enter] key to exit..."
        exit 1
    fi
fi

echo ""
echo "[INFO] Launching $ENTRY_POINT ..."
echo ""

if grep -qi "streamlit" pyproject.toml 2>/dev/null; then
    uv run streamlit run "$ENTRY_POINT" --server.headless false
else
    uv run python "$ENTRY_POINT"
fi

if [ $? -ne 0 ]; then
    echo ""
    echo "[WARNING] Application encountered an error or stopped."
fi

echo ""
read -p "Press [Enter] key to exit..."

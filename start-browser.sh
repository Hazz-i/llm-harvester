#!/usr/bin/env bash
# ==============================================================================
# Launch Brave / Chrome with remote debugging on port 9222
# Automatically extracts the DevTools WebSocket URL and updates LLM_CDP_WS in .env
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="9222"
DATA_DIR="$SCRIPT_DIR/chrome-data"
ENV_FILE="$SCRIPT_DIR/.env"
RUN_BG=false

# Parse flags
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--bg" ] || [ "$arg" = "-d" ]; then
        RUN_BG=true
    else
        ARGS+=("$arg")
    fi
done

# Find browser (or use BROWSER env variable if set)
BROWSER="${BROWSER:-}"
if [ -z "$BROWSER" ]; then
    for candidate in brave-browser brave google-chrome google-chrome-stable chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1; then
            BROWSER="$candidate"
            break
        fi
    done
fi

if [ -z "$BROWSER" ]; then
    echo "[!] Error: No compatible browser found (brave-browser, google-chrome, or chromium)."
    exit 1
fi

update_env() {
    local ws="$1"
    if [ -f "$ENV_FILE" ]; then
        if grep -q "^LLM_CDP_WS=" "$ENV_FILE"; then
            sed -i "s|^LLM_CDP_WS=.*|LLM_CDP_WS=$ws|" "$ENV_FILE"
        else
            echo "LLM_CDP_WS=$ws" >> "$ENV_FILE"
        fi
    else
        echo "LLM_CDP_WS=$ws" > "$ENV_FILE"
    fi
}

# Check if browser is ALREADY running on port 9222
EXISTING_WS=$(curl -s --connect-timeout 1 "http://127.0.0.1:$PORT/json/version" 2>/dev/null | grep -o '"webSocketDebuggerUrl": *"[^"]*"' | cut -d'"' -f4 || true)

if [ -n "$EXISTING_WS" ]; then
    echo "[✓] Browser is already running on port $PORT."
    echo "[✓] DevTools WebSocket URL: $EXISTING_WS"
    update_env "$EXISTING_WS"
    echo "[✓] Updated LLM_CDP_WS in $ENV_FILE automatically!"
    exit 0
fi

mkdir -p "$DATA_DIR"
echo "[*] Launching $BROWSER with remote debugging on port $PORT..."
echo "[*] User data dir: $DATA_DIR"

# Background watcher to grab ws URL as soon as port opens
(
    for i in {1..60}; do
        WS=$(curl -s --connect-timeout 1 "http://127.0.0.1:$PORT/json/version" 2>/dev/null | grep -o '"webSocketDebuggerUrl": *"[^"]*"' | cut -d'"' -f4 || true)
        if [ -n "$WS" ]; then
            update_env "$WS"
            echo ""
            echo "=========================================================="
            echo "[✓] DevTools listening on: $WS"
            echo "[✓] Successfully filled LLM_CDP_WS in $ENV_FILE!"
            echo "=========================================================="
            exit 0
        fi
        sleep 0.3
    done
) &
WATCHER_PID=$!

if [ "$RUN_BG" = true ]; then
    nohup "$BROWSER" --remote-debugging-port="$PORT" --user-data-dir="$DATA_DIR" "${ARGS[@]}" >/dev/null 2>&1 &
    BROWSER_PID=$!
    echo "[*] Browser running in background (PID: $BROWSER_PID)."
    wait $WATCHER_PID 2>/dev/null || true
else
    trap 'kill $WATCHER_PID 2>/dev/null || true' EXIT INT TERM
    "$BROWSER" --remote-debugging-port="$PORT" --user-data-dir="$DATA_DIR" "${ARGS[@]}" 2>&1 | grep -v "Gtk-WARNING.*Theme parser error" | grep -v "Gtk-WARNING.*No property named" || true
fi

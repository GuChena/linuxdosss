#!/bin/sh
set -eu

DISPLAY_NUM="${DISPLAY_NUM:-99}"
export DISPLAY=":${DISPLAY_NUM}"

SCREEN_WIDTH="${SCREEN_WIDTH:-1280}"
SCREEN_HEIGHT="${SCREEN_HEIGHT:-800}"
SCREEN_DEPTH="${SCREEN_DEPTH:-24}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_CONTAINER_PORT="${NOVNC_CONTAINER_PORT:-6080}"
CHROME_USER_DATA="${CHROME_USER_DATA:-/app/chrome-data}"
MANUAL_LOGIN_URL="${MANUAL_LOGIN_URL:-https://linux.do/login}"

mkdir -p "$CHROME_USER_DATA" /tmp/runtime-root
chmod 700 /tmp/runtime-root
export XDG_RUNTIME_DIR=/tmp/runtime-root

cleanup() {
    for pid in ${CHROME_PID:-} ${WEBSOCKIFY_PID:-} ${X11VNC_PID:-} ${FLUXBOX_PID:-} ${XVFB_PID:-}; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
}

trap cleanup INT TERM EXIT

Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x${SCREEN_DEPTH}" -ac +extension RANDR &
XVFB_PID=$!
sleep 1

fluxbox >/tmp/fluxbox.log 2>&1 &
FLUXBOX_PID=$!

x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport "$VNC_PORT" -listen 0.0.0.0 >/tmp/x11vnc.log 2>&1 &
X11VNC_PID=$!

websockify --web=/usr/share/novnc "$NOVNC_CONTAINER_PORT" "localhost:${VNC_PORT}" >/tmp/novnc.log 2>&1 &
WEBSOCKIFY_PID=$!

echo "Manual login desktop is ready."
echo "Open noVNC: http://127.0.0.1:${NOVNC_CONTAINER_PORT}/vnc.html?autoconnect=true&resize=scale"
echo "Chrome profile: ${CHROME_USER_DATA}"

google-chrome \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --window-size="${SCREEN_WIDTH},${SCREEN_HEIGHT}" \
    --user-data-dir="$CHROME_USER_DATA" \
    "$MANUAL_LOGIN_URL" >/tmp/chrome.log 2>&1 &
CHROME_PID=$!

wait "$CHROME_PID" || true
echo "Chrome exited. Restart this container if you need to open it again."

wait "$WEBSOCKIFY_PID"

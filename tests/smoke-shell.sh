#!/bin/bash
# Start a separate headless GNOME session, never the user's live shell.
set -eu
PROJECT=$(cd "$(dirname "$0")/.." && pwd)
TEST_ROOT=$(mktemp -d /tmp/monitor-presets-shell.XXXXXX)
export XDG_CONFIG_HOME="$TEST_ROOT/config"
export XDG_DATA_HOME="$TEST_ROOT/data"
export XDG_CACHE_HOME="$TEST_ROOT/cache"
export XDG_RUNTIME_DIR="$TEST_ROOT/runtime"
export XDG_SESSION_ID="monitor-presets-test"
export GSETTINGS_SCHEMA_DIR="$TEST_ROOT/schemas"
export PROJECT TEST_ROOT
mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME/gnome-shell/extensions" "$XDG_CACHE_HOME" "$XDG_RUNTIME_DIR" "$GSETTINGS_SCHEMA_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
cp "$PROJECT"/extension/schemas/*.xml "$GSETTINGS_SCHEMA_DIR/"
glib-compile-schemas --strict "$GSETTINGS_SCHEMA_DIR"
sh "$PROJECT/package.sh"
mkdir -p "$XDG_DATA_HOME/gnome-shell/extensions/monitor-presets-test@local"
cp "$PROJECT/tests/shell-driver.js" "$XDG_DATA_HOME/gnome-shell/extensions/monitor-presets-test@local/extension.js"
cat > "$XDG_DATA_HOME/gnome-shell/extensions/monitor-presets-test@local/metadata.json" <<'METADATA'
{"uuid":"monitor-presets-test@local","name":"Test driver","description":"Isolated smoke test","shell-version":["50"],"session-modes":["user","unlock-dialog"]}
METADATA
unset WAYLAND_DISPLAY DISPLAY DBUS_SESSION_BUS_ADDRESS
dbus-run-session -- bash <<'SESSION'
set -eu
gnome-extensions install "$PROJECT/dist/monitor-presets@local.shell-extension.zip"
test -f "$XDG_DATA_HOME/gnome-shell/extensions/monitor-presets@local/schemas/gschemas.compiled"
gsettings set org.gnome.shell enabled-extensions "['monitor-presets@local']"
gsettings set org.gnome.shell.extensions.monitor-presets restore-at-login false
gnome-shell --headless --wayland --no-x11 --virtual-monitor 1920x1080 \
    --virtual-monitor 1600x900 --virtual-monitor 1280x720 >"$TEST_ROOT/shell.log" 2>&1 &
SHELL_PID=$!
trap 'kill "$SHELL_PID" 2>/dev/null || true' EXIT
for attempt in $(seq 1 30); do
    if gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
        --method org.gnome.Shell.Extensions.GetExtensionInfo monitor-presets@local >"$TEST_ROOT/info.txt" 2>/dev/null; then
        if grep -q "'state': <1.0>" "$TEST_ROOT/info.txt"; then
            break
        fi
    fi
    if ! kill -0 "$SHELL_PID" 2>/dev/null; then
        cat "$TEST_ROOT/shell.log"
        exit 1
    fi
    sleep 1
done
cat "$TEST_ROOT/info.txt"
/usr/bin/python3 "$PROJECT/extension/backend.py" verify-current
/usr/bin/python3 "$PROJECT/tests/virtual-layouts.py"
/usr/bin/python3 "$PROJECT/extension/backend.py" save 'Virtual test'
gnome-extensions enable monitor-presets-test@local
# Exercise KVM preferences with a saved device and selected preset.
/usr/bin/python3 - <<'KVMCONFIG'
import json, os
from pathlib import Path
from gi.repository import Gio
settings = Gio.Settings.new('org.gnome.shell.extensions.monitor-presets')
db = json.loads((Path(os.environ['XDG_CONFIG_HOME']) / 'monitor-presets/presets.json').read_text())
settings.set_string('kvm-config', json.dumps({'usb': {'vendor': 'ffff', 'product': 'ffff', 'serial': 'test'},
                                           'preset': db['presets'][0]['id'], 'outputs': []}))
Gio.Settings.sync()
KVMCONFIG
GSETTINGS_BACKEND=memory gjs -m "$PROJECT/tests/preferences-autosave.js"
gnome-extensions prefs monitor-presets@local >"$TEST_ROOT/prefs.log" 2>&1 &
for attempt in $(seq 1 20); do
    if test -f "$TEST_ROOT/driver-result.json"; then break; fi
    sleep 1
done
cat "$TEST_ROOT/driver-result.json"
/usr/bin/python3 -c 'import json, os; assert json.load(open(os.environ["TEST_ROOT"] + "/driver-result.json")).get("ok")'
# Regression: user buses and runtime directories can survive logout/login.
/usr/bin/python3 "$PROJECT/extension/backend.py" startup last
gsettings set org.gnome.shell enabled-extensions "['monitor-presets@local']"
kill "$SHELL_PID"
wait "$SHELL_PID" || true
unset XDG_SESSION_ID
gnome-shell --headless --wayland --no-x11 --virtual-monitor 1920x1080 \
    --virtual-monitor 1600x900 --virtual-monitor 1280x720 >"$TEST_ROOT/second-shell.log" 2>&1 &
SHELL_PID=$!
for attempt in $(seq 1 30); do
    if gdbus call --session --dest org.gnome.Mutter.DisplayConfig \
        --object-path /org/gnome/Mutter/DisplayConfig \
        --method org.gnome.Mutter.DisplayConfig.GetCurrentState >/dev/null 2>&1; then break; fi
    sleep 1
done
/usr/bin/python3 "$PROJECT/tests/login-restore.py"
/usr/bin/python3 "$PROJECT/tests/prepare-native-login.py"
# Disable extensions before restart to prove Mutter itself reads the saved layout.
gsettings set org.gnome.shell enabled-extensions "[]"
kill "$SHELL_PID"
wait "$SHELL_PID" || true
gnome-shell --headless --wayland --no-x11 --virtual-monitor 1920x1080 \
    --virtual-monitor 1600x900 --virtual-monitor 1280x720 >"$TEST_ROOT/native-shell.log" 2>&1 &
SHELL_PID=$!
for attempt in $(seq 1 30); do
    if gdbus call --session --dest org.gnome.Mutter.DisplayConfig \
        --object-path /org/gnome/Mutter/DisplayConfig \
        --method org.gnome.Mutter.DisplayConfig.GetCurrentState >/dev/null 2>&1; then break; fi
    sleep 1
done
/usr/bin/python3 "$PROJECT/tests/check-native-login.py"
cat "$TEST_ROOT/prefs.log"
cat "$TEST_ROOT/shell.log"
SESSION
echo "Isolated session logs: $TEST_ROOT"

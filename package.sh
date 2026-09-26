#!/bin/sh
set -eu
cd "$(dirname "$0")"
project=$(pwd)
mkdir -p dist
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT HUP INT TERM
/usr/bin/python3 - "$project" "$stage" <<'PY'
from pathlib import Path
import shutil
import sys
source, stage = map(Path, sys.argv[1:])
shutil.copytree(source / 'extension', stage / 'extension',
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'gschemas.compiled'))
for name in ('LICENSE', 'NOTICE.md'):
    shutil.copy2(source / name, stage / 'extension' / name)
PY
glib-compile-schemas --strict "$stage/extension/schemas"
gnome-extensions pack --force --out-dir="$project/dist" \
    --extra-source=backend.py --extra-source=model.py --extra-source=client.js \
    --extra-source=preview.js --extra-source=native.py --extra-source=kvm.js \
    --extra-source=kvm.py --extra-source=inputs.py --extra-source=msi.py \
    --extra-source=input_actions.py --extra-source=inputShortcuts.js \
    --extra-source=audio.py --extra-source=controls.py --extra-source=monitorControls.js \
    --extra-source=inputPrefs.js --extra-source=monitor_drivers \
    --extra-source=LICENSE --extra-source=NOTICE.md "$stage/extension"

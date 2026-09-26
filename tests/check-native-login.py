"""Check the fresh compositor before the extension gets to apply its fallback."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import backend

assert '/tmp/monitor-presets-shell.' in os.environ['XDG_RUNTIME_DIR']
display = backend.Display()
db = backend.read_json(backend.ROOT / 'presets.json')
target = next(p['layout'] for p in db['presets'] if p['id'] == 'native-login')
current = display.capture()
assert len(current['logical']) == 1, 'Mutter did not load the native one-monitor default'
assert backend.signature(current)[:3] == backend.signature(target)[:3]
with patch.object(display, 'call', wraps=display.call) as call:
    display.apply(target)
    assert not any(c.args[0] == 'ApplyMonitorsConfig' for c in call.call_args_list), 'Matching layout was reapplied'
print('PASS: native configuration loaded before extension startup; no redundant modeset')

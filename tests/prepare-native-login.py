"""Prepare a native single-monitor default without applying it to this compositor."""
import copy
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import backend
from gi.repository import Gio

assert '/tmp/monitor-presets-shell.' in os.environ['XDG_RUNTIME_DIR']
display = backend.Display()
layout = copy.deepcopy(display.capture())
assert len(layout['logical']) == 3
layout['logical'] = [next(g for g in layout['logical'] if g['primary'])]
layout['logical'][0]['x'] = layout['logical'][0]['y'] = 0
db = backend.read_json(backend.ROOT / 'presets.json')
db['presets'].append({'id': 'native-login', 'name': 'Native login', 'layout': layout,
                      'inputs': [], 'claim_inputs': False})
db['last'] = 'native-login'
backend.write_json(backend.ROOT / 'presets.json', db)
settings = backend.login_settings()
settings.set_boolean('restore-at-login', True)
settings.set_string('startup-policy', 'last')
Gio.Settings.sync()
assert backend.sync_native(display, db)['native_updated']
assert len(display.capture()['logical']) == 3, 'Saving the native default must not change the current layout'
print('PASS: native login configuration saved without applying it')

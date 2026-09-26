"""Run after replacing the compositor on the same private user bus/runtime dir."""
import argparse
import copy
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import backend

assert '/tmp/monitor-presets-shell.' in os.environ['XDG_RUNTIME_DIR']
display = backend.Display()
old = backend.read_json(Path(os.environ['XDG_RUNTIME_DIR']) / 'monitor-presets-startup.json')
assert old and old['session'] != display.session_key(), 'New compositor must have a new startup identity'
db = backend.read_json(backend.ROOT / 'presets.json')
single = copy.deepcopy(display.capture())
single['logical'] = [next(g for g in single['logical'] if g['primary'])]
single['logical'][0]['x'] = single['logical'][0]['y'] = 0
display.apply(single)
args = argparse.Namespace(command='startup', value='last')
result = backend.execute(args, display, db)
assert result.get('message') == 'Login layout restored', result
assert len(display.capture()['logical']) == 3
assert backend.execute(args, display, db).get('reason') == 'already-restored-this-compositor'
print('PASS: fresh compositor restores last three-display preset with persistent user bus/runtime directory')

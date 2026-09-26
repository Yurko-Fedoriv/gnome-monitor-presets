"""Integration test called only inside smoke-shell.sh's private GNOME session."""
import argparse
import copy
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extension"))
import backend
from model import signature

assert os.environ.get("XDG_SESSION_ID") == "monitor-presets-test", "Requires isolated smoke-test session"
assert "/tmp/monitor-presets-shell." in os.environ["XDG_RUNTIME_DIR"]
display = backend.Display()
all_displays = display.capture()
assert len(all_displays["logical"]) == 3
single = copy.deepcopy(all_displays)
single["logical"] = [next(g for g in single["logical"] if g["primary"])]
single["logical"][0]["x"] = single["logical"][0]["y"] = 0
display.apply(single, verify=True)
display.apply(single)
assert len(display.capture()["logical"]) == 1, "Other virtual displays were not disabled"
display.apply(all_displays)
assert signature(display.capture()) == signature(all_displays), "Exact restore failed"
# Exercise the actual independent watchdog process, with a shortened test deadline.
display.apply(single)
backend.write_json(backend.pending_path(), {"token": "watchdog-test", "before": all_displays,
    "target_id": None, "deadline": time.time() + 0.5})
subprocess.run([sys.executable, str(Path(backend.__file__)), "watchdog", "watchdog-test"], check=True)
assert signature(display.capture()) == signature(all_displays), "Watchdog did not restore all displays"
assert not backend.pending_path().exists()
assert display.session_key() == backend.Display().session_key(), "Session key changed between helpers"
print("PASS: three displays → one display → exact restore; independent watchdog recovery")

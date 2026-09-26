#!/usr/bin/python3
"""Monitor Presets helper. All shell calls use argv, never a shell interpreter."""
import argparse
import copy
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from gi.repository import Gio, GLib
from model import snapshot, resolve, signature
import native
from monitor_drivers.generic_ddc import read_input
from monitor_drivers import select as monitor_driver, transport as input_transport, update_options

NAME = "org.gnome.Mutter.DisplayConfig"
OBJECT = "/org/gnome/Mutter/DisplayConfig"
ROOT = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "monitor-presets"
LOG = logging.getLogger("monitor-presets")
PREFS = {"org.gnome.mutter": ["output-luminance"],
         "org.gnome.settings-daemon.plugins.color": ["night-light-enabled", "night-light-temperature",
             "night-light-schedule-automatic", "night-light-schedule-from", "night-light-schedule-to"],
         "org.gnome.desktop.privacy": ["privacy-screen"]}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".presets-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text())


def schema_settings(schema):
    source = Gio.SettingsSchemaSource.get_default()
    found = source.lookup(schema, True)
    return (Gio.Settings.new_full(found, None, None), found) if found else (None, None)


def login_settings():
    source = Gio.SettingsSchemaSource.new_from_directory(str(Path(__file__).parent / 'schemas'),
        Gio.SettingsSchemaSource.get_default(), False)
    return Gio.Settings.new_full(source.lookup('org.gnome.shell.extensions.monitor-presets', False), None, None)


def sync_native(display, db):
    settings = login_settings()
    if not settings.get_boolean('restore-at-login'):
        return {'ok': True, 'reason': 'login-restore-disabled'}
    wanted = settings.get_string('fixed-preset') if settings.get_string('startup-policy') == 'fixed' else db.get('last')
    preset = next((p for p in db['presets'] if p['id'] == wanted), None)
    if not preset:
        return {'ok': True, 'reason': 'no-login-preset'}
    state = display.state()
    try:
        layout = resolve(preset['layout'], state)
        layout['connected'] = [list(m[0]) for m in state[1]]
    except ValueError:
        # Preserve the original hardware combination when its monitors are away.
        layout = preset['layout']
    changed = native.sync(ROOT.parent / 'monitors.xml', layout, ROOT / 'native-backups')
    return {'ok': True, 'native_updated': changed, 'preset': wanted}


class Display:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, method, params=None, interface=NAME):
        return self.bus.call_sync(NAME, OBJECT, interface, method, params, None,
                                  Gio.DBusCallFlags.NONE, 15000, None).unpack()

    def state(self):
        return self.call("GetCurrentState")

    def session_key(self):
        # The user bus/runtime directory can survive logout. Its unique name for
        # Mutter changes with each compositor, but survives extension re-enables.
        def bus_call(method, params=None):
            return self.bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                'org.freedesktop.DBus', method, params, None,
                Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        bus_id = bus_call('GetId')
        owner = bus_call('GetNameOwner', GLib.Variant('(s)', (NAME,)))
        return hashlib.sha256(f'{bus_id}:{owner}'.encode()).hexdigest()

    def capture(self):
        result = snapshot(self.state())
        result["preferences"] = {}
        for schema, keys in PREFS.items():
            settings, definition = schema_settings(schema)
            if settings:
                result["preferences"][schema] = {key: settings.get_value(key).print_(True)
                    for key in keys if definition.has_key(key)}
        result["backlights"] = []
        try:
            serial, backlights = self.call("Get", GLib.Variant("(ss)", (NAME, "Backlight")),
                                          "org.freedesktop.DBus.Properties")[0]
            for backlight in backlights:
                if "value" in backlight:
                    spec = next((s for s in result["connected"] if s[0] == backlight["connector"]), None)
                    if spec:
                        result["backlights"].append({"spec": spec, "value": backlight["value"]})
        except GLib.Error:
            pass  # External screens normally have no compositor backlight interface.
        return result

    def apply(self, saved, verify=False):
        state = self.state()
        resolved = resolve(saved, state)
        groups = []
        for g in resolved["logical"]:
            ms = [(m["spec"][0], m["mode"], {k: GLib.Variant("b" if isinstance(v, bool) else "u", v)
                    for k, v in m["options"].items()}) for m in g["monitors"]]
            groups.append((g["x"], g["y"], g["scale"], g["transform"], g["primary"], ms))
        properties = {"monitors-for-lease": GLib.Variant("a(ssss)", resolved["leased"])}
        if state[3].get("supports-changing-layout-mode"):
            properties["layout-mode"] = GLib.Variant("u", resolved["layout_mode"])
        # Preferences are restored separately; they must not force a modeset.
        layout_changed = signature(snapshot(state))[:3] != signature(resolved)[:3]
        if verify or layout_changed:
            LOG.info('Display layout %s', 'verify' if verify else 'apply')
            self.call("ApplyMonitorsConfig", GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})",
                      (state[0], 0 if verify else 1, groups, properties)))
        else:
            LOG.info('Display layout already matches; applying only changed preferences')
        if verify:
            return
        for schema, values in saved.get("preferences", {}).items():
            settings, definition = schema_settings(schema)
            if settings:
                for key, value in values.items():
                    if key in PREFS.get(schema, []) and definition.has_key(key):
                        variant = GLib.Variant.parse(settings.get_value(key).get_type(), value, None, None)
                        if settings.get_value(key).equal(variant):
                            continue
                        if not settings.set_value(key, variant):
                            raise ValueError(f"Unable to restore {key}")
        Gio.Settings.sync()
        if saved.get("backlights"):
            from model import match_monitor
            serial, backlights = self.call("Get", GLib.Variant("(ss)", (NAME, "Backlight")),
                                  "org.freedesktop.DBus.Properties")[0]
            for item in saved["backlights"]:
                live = match_monitor(item["spec"], self.state()[1])
                if any(b.get('connector') == live[0][0] and b.get('value') == item['value'] for b in backlights):
                    continue
                self.call("SetBacklight", GLib.Variant("(usi)", (serial, live[0][0], item["value"])))


def drm_displays():
    result = []
    for path in Path("/sys/class/drm").glob("card*-*"):
        try:
            edid = (path / "edid").read_bytes()
            if not edid:
                continue
            connector = path.name.split("-", 1)[1].replace("HDMI-A-", "HDMI-")
            ddc = (path / "ddc").resolve()
            bus = int(ddc.name.removeprefix("i2c-")) if ddc.name.startswith("i2c-") else None
            result.append({"connector": connector, "edid": hashlib.sha256(edid).hexdigest(), "bus": bus})
        except (OSError, ValueError):
            continue
    return result


def _claim_inputs(preset):
    mappings = preset.get("inputs", [])
    errors = []
    results = []
    displays = drm_displays()
    profiles = read_json(ROOT / 'input-transports.json', {})
    known = {m['spec'][0]: monitor_driver(m['spec'])
             for group in preset.get('layout', {}).get('logical', []) for m in group['monitors']}
    for mapping in mappings:
        report = {"connector": mapping["connector"], "target": mapping["code"]}
        results.append(report)
        found = [d for d in displays if d["edid"] == mapping["edid"]]
        if len(found) != 1 or found[0]["bus"] is None:
            errors.append(f"{mapping['connector']}: DDC connection unavailable or ambiguous")
            report["error"] = errors[-1]
            continue
        try:
            code = int(mapping["code"])
            if code < 1 or code > 255:
                raise ValueError("Input code must be between 1 and 255")
            bus = found[0]["bus"]
            report["bus"] = bus
            profile = mapping.get('profile', profiles.get(mapping['edid'], {}))
            driver = known.get(mapping['connector'])
            name = profile.get('transport', driver.default_transport if driver else 'standard')
            report['transport'] = name
            implementation = input_transport(name)
            if driver and not driver.allows_transport(name):
                raise ValueError('Unsupported input transport for this monitor')
            implementation.switch(code, bus, profile, report, read_input)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            report["status"] = "failed"
            report["error"] = str(error)
            if "ENXIO" in str(error):
                detail = "Monitor did not respond. Wake it on its current input and try again."
            elif isinstance(error, subprocess.TimeoutExpired):
                detail = "Monitor communication timed out."
            elif isinstance(error, FileNotFoundError):
                detail = "ddcutil is not installed or is not on PATH."
            else:
                detail = str(error).strip().splitlines()[-1]
            errors.append(f"{mapping['connector']}: {detail}")
    return errors, results


def claim_inputs(preset, manual=False):
    from concurrent.futures import ThreadPoolExecutor
    mappings = preset.get('inputs', [])
    if (not manual and not preset.get('claim_inputs')) or not mappings:
        return []
    # Independent buses can progress together; never race commands on one bus.
    displays = drm_displays()
    groups = {}
    for mapping in mappings:
        matches = [d for d in displays if d['edid'] == mapping['edid']]
        bus = matches[0]['bus'] if len(matches) == 1 else None
        groups.setdefault(bus, []).append(mapping)
    with ThreadPoolExecutor(max_workers=min(8, len(groups))) as workers:
        batches = list(workers.map(_claim_inputs,
            [{**preset, 'inputs': group} for group in groups.values()]))
    errors = [error for batch, _ in batches for error in batch]
    results = [result for _, batch in batches for result in batch]
    # Only the calling thread writes the combined report.
    write_json(ROOT / 'last-input-check.json', {'time': time.time(), 'results': results})
    LOG.info('Input check: %s', json.dumps(results))
    return errors


def pending_path():
    return ROOT / "pending.json"


def rollback(display, db, token):
    pending = read_json(pending_path())
    if not pending or pending["token"] != token:
        return {"ok": True}
    # Keep the recovery snapshot on failure; never silently discard it.
    display.apply(pending["before"])
    pending_path().unlink(missing_ok=True)
    return {"ok": True, "message": "Previous display layout restored"}


def activate(display, db, target, preset_id=None, require_confirmation=True):
    if pending_path().exists():
        raise ValueError("Keep or revert the pending display change first")
    display.apply(target, verify=True)
    before = display.capture()
    token = str(uuid.uuid4())
    pending = {"token": token, "before": before, "target_id": preset_id,
               "deadline": time.time() + 30}
    write_json(pending_path(), pending)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watchdog", token],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    try:
        display.apply(target)
    except Exception:
        rollback(display, db, token)
        raise
    if not require_confirmation:
        return commit(display, db, token)
    return {"ok": True, "token": token, "deadline": pending["deadline"],
            "message": "Keep this display layout? It will revert automatically in 30 seconds."}


def commit(display, db, token):
    pending = read_json(pending_path())
    if not pending or pending["token"] != token:
        raise ValueError("Display change already reverted")
    if time.time() >= pending["deadline"]:
        rollback(display, db, token)
        raise ValueError("Confirmation expired; previous layout restored")
    db["previous"] = pending["before"]
    if pending["target_id"]:
        db["last"] = pending["target_id"]
    write_json(ROOT / "presets.json", db)
    pending_path().unlink()
    return {"ok": True, "warnings": [], "message": "Layout applied"}


def perform_action(action, display, db, suppress):
    from input_actions import route
    if pending_path().exists():
        return {'ok': True, 'skipped': 'layout confirmation pending'}
    # Cross-process guard prevents a second trigger queued during a running action
    # from executing when the helper lock becomes available.
    requested = float(os.environ.get('MONITOR_ACTION_REQUESTED', time.time()))
    previous = read_json(ROOT / 'last-action.json', {})
    if previous.get('finished', 0) > requested:
        return {'ok': True, 'skipped': 'overlapping action'}
    settings = login_settings()
    skipped = []
    layout_applied = False
    preset = next((p for p in db['presets'] if p['id'] == action.get('preset')), None)
    if action.get('preset') and not preset:
        skipped.append('Preset no longer exists')
    if preset:
        try:
            display.apply(preset['layout'], verify=True)
        except Exception as error:
            skipped.append(str(error))
            preset = None
    if suppress:
        # Arm before input writes; the watcher consumes this once on an away edge.
        settings.set_double('action-suppress-kvm-until', time.time() + 60)
        Gio.Settings.sync()
    try:
        current = display.capture()
        devices = drm_displays()
        cache = read_json(ROOT / 'input-capabilities.json', {})
        mappings = []
        for output in action.get('outputs', []):
            try:
                request = route(output, current, db['presets'], devices, cache)
                mappings.extend(request["inputs"])
            except (ValueError, OSError) as error:
                skipped.append(str(error))
        skipped.extend(claim_inputs({'inputs': mappings, 'layout': current}, manual=True))
        if preset:
            try:
                activate(display, db, preset['layout'], preset['id'], require_confirmation=False)
                layout_applied = True
            except Exception as error:
                skipped.append(str(error))
        return {'ok': True, 'skipped_monitors': skipped, 'layout_applied': layout_applied}
    finally:
        if suppress and settings.get_double('action-suppress-kvm-until') > time.time():
            settings.set_double('action-suppress-kvm-until', time.time() + 5)
            Gio.Settings.sync()
        write_json(ROOT / 'last-action.json', {'id': action['id'], 'finished': time.time()})


def execute(args, display, db):
    command = args.command
    if command in ('monitor-controls', 'set-monitor-control'):
        import controls
        return controls.execute(json.loads(args.value), display.capture(), drm_displays(),
                                write=command == 'set-monitor-control')
    if command in ('input-targets', 'refresh-action-inputs', 'monitor-profile'):
        from input_actions import all_targets
        from inputs import describe, refresh, identity
        devices = drm_displays()
        available = all_targets(display.capture(), db['presets'], devices)
        cache = read_json(ROOT / 'input-capabilities.json', {})
        updated, warnings = (0, [])
        if command == 'monitor-profile':
            profile = json.loads(args.value)
            target = next(t for t in available if t['spec'] == profile['spec'])
            key = identity(target['spec'])
            cache[key] = update_options(target['spec'], cache.get(key, {}),
                                        {k: v for k, v in profile.items() if k != 'spec'})
            write_json(ROOT / 'input-capabilities.json', cache)
        if command == 'refresh-action-inputs':
            updated, warnings = refresh(available, devices, cache)
            write_json(ROOT / 'input-capabilities.json', cache)
        return {'targets': [describe(t, cache) for t in available],
                'updated': updated, 'warnings': warnings}
    if command == 'action-state':
        from input_actions import load
        from msi import devices
        return {'actions': load(login_settings()), 'controllers': devices()}
    if command == 'run-action':
        from input_actions import load
        action = next((a for a in load(login_settings()) if a.get('id') == args.value), None)
        if not action:
            return {'ok': True, 'skipped': 'action removed'}
        return perform_action(action, display, db, suppress=True)
    if command in ('kvm-targets', 'refresh-inputs', 'input-profile'):
        from kvm import targets
        preset = next(p for p in db['presets'] if p['id'] == args.value)
        from inputs import describe, refresh, identity
        devices = drm_displays()
        available = targets(preset, display.capture(), db['presets'], devices)
        cache = read_json(ROOT / 'input-capabilities.json', {})
        warnings = []
        updated = 0
        if command == 'refresh-inputs':
            updated, warnings = refresh(available, devices, cache)
            write_json(ROOT / 'input-capabilities.json', cache)
        elif command == 'input-profile':
            profile = json.loads(args.extra)
            target = next(t for t in available if t['spec'] == profile['spec'])
            key = identity(target['spec'])
            cache[key] = update_options(target['spec'], cache.get(key, {}),
                                        {k: v for k, v in profile.items() if k != 'spec'})
            write_json(ROOT / 'input-capabilities.json', cache)
        return {'targets': [describe(t, cache) for t in available],
                'updated': updated, 'warnings': warnings}
    if command == 'kvm-disconnect':
        from kvm import usb_present
        settings = login_settings()
        config = json.loads(settings.get_string('kvm-config'))
        if (not settings.get_boolean('kvm-disconnect-enabled') or
                settings.get_double('kvm-detect-until') > time.time()):
            return {'ok': True, 'skipped': 'disabled or detecting'}
        if not config.get('usb') or usb_present(config['usb']):
            return {'ok': True, 'skipped': 'USB present or not configured'}
        if settings.get_double('action-suppress-kvm-until') > time.time():
            settings.set_double('action-suppress-kvm-until', 0)
            return {'ok': True, 'skipped': 'action-induced disconnect'}
        from input_actions import load
        action = next((a for a in load(settings) if any(t.get('type') == 'kvm' for t in a.get('triggers', []))), None)
        if not action:
            return {'ok': True, 'skipped': 'no disconnect action'}
        return perform_action(action, display, db, suppress=False)
    if command == 'sync-native':
        return sync_native(display, db)
    if command == "status":
        current = display.capture()
        matches = [p for p in db["presets"] if signature(p["layout"]) == signature(current)]
        active = next((p["id"] for p in matches if p["id"] == db.get("last")),
                      matches[0]["id"] if matches else None)
        presets = []
        state = display.state()
        for preset in db["presets"]:
            item = copy.deepcopy(preset)
            try:
                resolve(preset["layout"], state)
                item["unavailable"] = None
            except ValueError as error:
                item["unavailable"] = str(error)
            presets.append(item)
        return {"presets": presets, "active": active, "current": current,
                "previous": bool(db.get("previous")), "last": db.get("last"),
                "pending": read_json(pending_path()), "ddc": drm_displays()}
    if command == "save":
        name = args.value.strip()
        if not name or len(name) > 80:
            raise ValueError("Use a name of 1–80 characters")
        layout = display.capture()
        preset = {"id": str(uuid.uuid4()), "name": name, "layout": layout}
        db["presets"].append(preset)
        return {"ok": True, "id": preset["id"]}
    if command == "verify-current":
        display.apply(display.capture(), verify=True)
        return {"ok": True, "message": "Current layout round-trip accepted by Mutter (verify only)"}
    if command == "export-current":
        return display.capture()
    if command == "apply":
        preset = next(p for p in db["presets"] if p["id"] == args.value)
        return activate(display, db, preset["layout"], preset["id"],
                        require_confirmation=getattr(args, "extra", "") != "immediate")
    if command == "undo":
        if not db.get("previous"):
            raise ValueError("No previous layout has been saved")
        return activate(display, db, db["previous"],
                        require_confirmation=getattr(args, "extra", "") != "immediate")
    if command == "revert":
        return rollback(display, db, args.value)
    if command == "confirm":
        return commit(display, db, args.value)
    if command in ("rename", "delete", "move", "update"):
        if pending_path().exists():
            raise ValueError("Keep or revert the pending display change first")
        preset = next(p for p in db["presets"] if p["id"] == args.value)
        if command == "rename":
            name = args.extra.strip()
            if not name or len(name) > 80:
                raise ValueError("Use a name of 1–80 characters")
            preset["name"] = name
        elif command == "delete":
            db["presets"].remove(preset)
        elif command == "update":
            preset["layout"] = display.capture()
        elif command == "move":
            index = db["presets"].index(preset)
            new = max(0, min(len(db["presets"]) - 1, index + int(args.extra)))
            db["presets"].insert(new, db["presets"].pop(index))
        return {"ok": True}
    if command == "startup":
        session = display.session_key()
        stamp = Path(os.environ["XDG_RUNTIME_DIR"]) / "monitor-presets-startup.json"
        if read_json(stamp, {}).get("session") == session:
            return {"ok": True, "skipped": True, "reason": "already-restored-this-compositor"}
        if pending_path().exists():
            pending = read_json(pending_path())
            rollback(display, db, pending["token"])
        wanted = args.value if args.value != "last" else db.get("last")
        preset = next((p for p in db["presets"] if p["id"] == wanted), None)
        if not preset:
            return {"ok": True, "skipped": True, "reason": "no-login-preset", "requested": wanted}
        before = display.capture()
        if signature(before) == signature(preset["layout"]):
            write_json(stamp, {"session": session, "preset": wanted})
            return {"ok": True, "skipped": True, "message": "Login layout already matches",
                    "preset": preset["id"], "warnings": []}
        display.apply(preset["layout"], verify=True)
        try:
            display.apply(preset["layout"])
        except Exception:
            display.apply(before)
            raise
        write_json(stamp, {"session": session, "preset": wanted})
        return {"ok": True, "message": "Login layout restored", "preset": preset["id"],
                "warnings": []}
    raise ValueError(f"Unknown command: {command}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("value", nargs="?", default="")
    parser.add_argument("extra", nargs="?", default="")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(ROOT / "diagnostics.log", maxBytes=262144, backupCount=1)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    if args.command == "watchdog":
        pending = read_json(pending_path())
        if pending and pending["token"] == args.value:
            time.sleep(max(0, pending["deadline"] - time.time()))
        args.command = "revert"
    with (ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        db = read_json(ROOT / "presets.json", {"version": 1, "presets": []})
        if db.get("version") != 1:
            raise ValueError("Unsupported preset file version")
        result = execute(args, Display(), db)
        if (args.command in ('apply', 'confirm', 'undo', 'startup', 'update', 'delete') or
                (args.command in ('kvm-disconnect', 'run-action') and result.get('layout_applied'))) and not pending_path().exists():
            try:
                result['native_sync'] = sync_native(Display(), db)
            except Exception as error:
                LOG.exception('Native login layout sync failed')
                result.setdefault('warnings', []).append(f'Could not save login layout: {error}')
        if args.command not in ("status", "export-current", "kvm-targets"):
            LOG.info("%s: %s", args.command, json.dumps(result))
        if args.command not in ("monitor-controls", "set-monitor-control", "status", "export-current", "verify-current", "revert", "startup", "sync-native", "kvm-targets", "kvm-disconnect", "refresh-inputs", "input-profile", "input-targets", "refresh-action-inputs", "switch-input", "action-state", "run-action", "monitor-profile"):
            write_json(ROOT / "presets.json", db)
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        LOG.exception("Helper failed: %s", sys.argv[1:2])
        print(json.dumps({"error": str(error) or type(error).__name__}))
        sys.exit(1)

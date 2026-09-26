"""Cache monitor input discovery by identity; delegate hardware rules to drivers."""
import subprocess
import time
from monitor_drivers import select, options
from monitor_drivers.generic_ddc import parse_capabilities


def identity(spec):
    import json
    return json.dumps(spec[1:], separators=(',', ':'))


def choices(spec, cache):
    return select(spec).choices(cache.get(identity(spec), {}))


def describe(target, cache):
    from controls import cached
    entry = cache.get(identity(target['spec']), {})
    return {**target, 'inputs': choices(target['spec'], cache),
            'controls': cached(target['spec'], target.get('edid'), cache),
            'controls_probed': entry.get('controls_updated'),
            'probed': entry.get('updated'), 'usb_c': bool(entry.get('usb_c')),
            'options': options(target['spec'], entry)}


def refresh(targets, displays, cache):
    warnings = []
    updated = 0
    for target in targets:
        try:
            result = select(target['spec']).discover(target, displays)
            key = identity(target['spec'])
            cache[key] = {**cache.get(key, {}), **result, 'updated': time.time(), 'edid': target['edid']}
            updated += 1
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            warnings.append(f"{target['connector']}: {error}; previous inputs retained")
    return updated, warnings

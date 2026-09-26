"""Monitor-owned DDC controls. No software brightness or mixer volume fallback."""
import os
import re
import subprocess

class UnsupportedControl(ValueError):
    pass


FEATURES = {'brightness': '10', 'volume': '62', 'mute': '8D'}


def command(bus, *args):
    result = subprocess.run(['ddcutil', '--bus', str(bus), '--brief', *args],
                            capture_output=True, text=True, timeout=6,
                            env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode and 'unsupported' in result.stdout.lower():
        raise UnsupportedControl('Control unsupported')
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Monitor did not respond')
    return result.stdout


def read(bus, feature):
    code = FEATURES[feature]
    output = command(bus, 'getvcp', code)
    if feature == 'mute':
        match = re.search(r'^VCP 8D SNC x([0-9a-f]+)\s*$', output, re.I | re.M)
        if match and int(match[1], 16) in (1, 2):
            return {'value': int(match[1], 16) == 1}
    else:
        match = re.search(rf'^VCP {code} C (\d+) (\d+)\s*$', output, re.I | re.M)
        if match:
            value, maximum = map(int, match.groups())
            if 0 <= value <= maximum <= 65535 and maximum > 0:
                return {'value': value, 'maximum': maximum}
    raise UnsupportedControl('Control unsupported or returned an unusable value')


def target(request, current, displays):
    spec = request.get('spec')
    if not any(m['spec'] == spec for g in current['logical'] for m in g['monitors']):
        raise ValueError('Monitor is no longer active')
    matches = [d for d in displays if d['connector'] == spec[0]
               and d['edid'] == request.get('edid') and d.get('bus') is not None]
    if len(matches) != 1:
        raise ValueError('Monitor DDC connection unavailable or changed')
    return matches[0]['bus']


def execute(request, current, displays, write=False):
    bus = target(request, current, displays)
    if write:
        feature, value = request.get('feature'), request.get('value')
        if feature not in FEATURES:
            raise ValueError('Unknown monitor control')
        state = read(bus, feature)  # Fresh support/range check; never trust UI limits.
        if feature == 'mute':
            if type(value) is not bool:
                raise ValueError('Mute must be boolean')
            raw = 1 if value else 2  # Audio only; never set screen-blank bits.
        else:
            if type(value) is not int or not 0 <= value <= state['maximum']:
                raise ValueError('Monitor control value out of range')
            raw = value
        command(bus, 'setvcp', FEATURES[feature], str(raw))
        return {'feature': feature, 'control': read(bus, feature)}
    controls, unavailable, failed = {}, {}, {}
    for feature in FEATURES:
        try:
            controls[feature] = read(bus, feature)
        except UnsupportedControl as error:
            unavailable[feature] = str(error)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            failed[feature] = str(error)
    return {'controls': controls, 'unavailable': unavailable, 'failed': failed}


def cached(spec, edid, cache):
    from inputs import identity
    entry = cache.get(identity(spec), {})
    if edid and entry.get('controls_edid') != edid:
        return {}
    return entry.get('controls', {})


def refresh(targets, current, displays, cache):
    """Explicit discovery only; retain known values on transient read failures."""
    from inputs import identity
    warnings = []
    for monitor in targets:
        try:
            result = execute(monitor, current, displays)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            warnings.append(f"{monitor['connector']}: {error}; previous controls retained")
            continue
        key = identity(monitor['spec'])
        entry = cache.setdefault(key, {})
        values = dict(cached(monitor['spec'], monitor['edid'], cache))
        values.update(result['controls'])
        for feature in result['unavailable']:
            values.pop(feature, None)
        import time
        entry.update(controls=values, controls_edid=monitor['edid'], controls_updated=time.time())
        if result['failed']:
            warnings.append(f"{monitor['connector']}: could not read " + ', '.join(result['failed']) + '; previous values retained')
    return warnings

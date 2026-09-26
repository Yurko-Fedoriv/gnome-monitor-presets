"""Validate KVM routing and reject stale USB transitions before sending DDC."""
from pathlib import Path


def usb_present(identity, root=Path('/sys/bus/usb/devices')):
    for device in root.iterdir():
        try:
            if ((device / 'idVendor').read_text().strip() == identity['vendor'] and
                    (device / 'idProduct').read_text().strip() == identity['product'] and
                    (not identity.get('serial') or
                     (device / 'serial').read_text().strip() == identity['serial']) and
                    (not identity.get('path') or device.name == identity['path'])):
                return True
        except OSError:
            continue
    return False


def targets(preset, current, presets, ddc):
    active = {tuple(m['spec'][1:]) for g in preset['layout']['logical'] for m in g['monitors']}
    known = {}
    for layout in [p['layout'] for p in presets] + [current]:
        for spec in layout.get('connected', []):
            known[tuple(spec[1:])] = spec
        for group in layout['logical']:
            for monitor in group['monitors']:
                known[tuple(monitor['spec'][1:])] = monitor['spec']
    result = []
    for spec in known.values():
        if tuple(spec[1:]) in active:
            continue
        matches = [d for d in ddc if d['connector'] == spec[0]]
        result.append({'spec': spec, 'connector': spec[0],
                       'edid': matches[0]['edid'] if len(matches) == 1 else None})
    return result


def redirect_preset(config, preset, current, presets, ddc, cache=None):
    from inputs import choices
    from monitor_drivers import select
    cache = cache or {}
    available = targets(preset, current, presets, ddc)
    mappings = []
    for mapping in config.get('outputs', []):
        matches = [t for t in available if t['spec'][1:] == mapping['spec'][1:]]
        if len(matches) != 1:
            raise ValueError('KVM destination is no longer excluded by the selected preset; save KVM settings again')
        target = matches[0]
        code = mapping['code']
        if type(code) is not int or code not in {c['code'] for c in choices(target['spec'], cache)}:
            raise ValueError('Unsupported KVM input destination')
        if not mapping.get('edid') or (target['edid'] and mapping['edid'] != target['edid']):
            raise ValueError('KVM monitor identity changed; save KVM settings again')
        item = {'connector': target['connector'], 'edid': mapping['edid'], 'code': code}
        driver = select(target['spec'])
        # This legacy endpoint historically adds only DDC profiles.
        if driver.channel == 'ddc':
            profile = driver.profile(code)
            if profile:
                item['profile'] = profile
        mappings.append(item)
    return {'inputs': mappings, 'layout': current}

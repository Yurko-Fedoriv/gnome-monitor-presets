"""Validate single-monitor input actions without touching layouts or KVM settings."""
from kvm import targets
from inputs import choices
from monitor_drivers import select


def all_targets(current, presets, devices):
    return targets({'layout': {'logical': []}}, current, presets, devices)


def route(action, current, presets, devices, cache):
    matches = [t for t in all_targets(current, presets, devices)
               if t['spec'][1:] == action.get('spec', [])[1:]]
    if len(matches) != 1:
        raise ValueError('Shortcut monitor is missing or ambiguous; select it again')
    target = matches[0]
    if not action.get('edid') or target['edid'] != action['edid']:
        raise ValueError('Shortcut monitor is disconnected or its identity changed; select it again')
    driver = select(target['spec'])
    driver.check_target(target, current)
    code = action.get('code')
    if type(code) is not int or code not in {c['code'] for c in choices(target['spec'], cache)}:
        raise ValueError('Select a supported input for this shortcut')
    mapping = {'connector': target['connector'], 'edid': target['edid'], 'code': code}
    profile = driver.profile(code)
    if profile:
        mapping['profile'] = profile
    return {'inputs': [mapping], 'layout': current}


def load(settings):
    import json
    import uuid
    if not settings.get_boolean('actions-migrated'):
        entries = json.loads(settings.get_string('monitor-actions'))
        if not entries:
            legacy = json.loads(settings.get_string('kvm-config'))
            if legacy.get('preset'):
                entries.append({'id': str(uuid.uuid4()), 'name': 'KVM disconnect',
                                'preset': legacy['preset'], 'outputs': legacy.get('outputs', []),
                                'triggers': [{'type': 'kvm'}]})
            for old in json.loads(settings.get_string('input-shortcuts')):
                entries.append({'id': old['id'], 'name': 'Input shortcut', 'preset': None,
                                'outputs': [{k: old[k] for k in ('spec', 'edid', 'code')}]
                                    if old.get('spec') and old.get('code') else [],
                                'triggers': [{'type': 'keyboard', 'accelerator': old['accelerator']}]
                                    if old.get('accelerator') else []})
            settings.set_string('monitor-actions', json.dumps(entries))
        settings.set_boolean('actions-migrated', True)
    return json.loads(settings.get_string('monitor-actions'))

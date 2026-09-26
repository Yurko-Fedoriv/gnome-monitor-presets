"""Read GNOME's HDMI/DisplayPort output choices without changing audio routing."""
import json
from pathlib import Path


def outputs():
    import gi
    from gi import _gi
    # GVC is shipped privately by GNOME Shell, outside the default GI paths.
    repository = _gi.Repository.get_default()
    for root in ('/usr/lib/gnome-shell', '/usr/lib64/gnome-shell'):
        if (Path(root) / 'Gvc-1.0.typelib').is_file():
            repository.prepend_search_path(root)
            repository.prepend_library_path(root)
            break
    gi.require_version('Gvc', '1.0')
    from gi.repository import Gvc, GLib
    control = Gvc.MixerControl(name='Monitor Presets capability discovery')
    loop = GLib.MainLoop()
    found = {}

    def added(_control, identifier):
        device = control.lookup_output_id(identifier)
        if not device:
            return
        port, origin, description = device.get_port(), device.get_origin(), device.get_description()
        if not any(word in f'{port} {description}'.lower() for word in ('hdmi', 'displayport')):
            return
        key = json.dumps([port, origin, description], separators=(',', ':'), ensure_ascii=False)
        found[identifier] = {'key': key, 'label': ' — '.join(x for x in (description, origin) if x)}

    def state_changed(_control, state):
        if state in (Gvc.MixerControlState.READY, Gvc.MixerControlState.FAILED):
            loop.quit()

    signals = [control.connect('output-added', added), control.connect('state-changed', state_changed)]
    timeout = GLib.timeout_add(3000, lambda: (loop.quit(), GLib.SOURCE_CONTINUE)[1])
    try:
        control.open()
        loop.run()
        # Ambiguous descriptions are not safe to save as unique associations.
        result = list(found.values())
        return [item for item in result if sum(x['key'] == item['key'] for x in result) == 1]
    finally:
        GLib.source_remove(timeout)
        for signal in signals:
            control.disconnect(signal)
        control.close()

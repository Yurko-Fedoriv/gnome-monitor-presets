"""Merge a login preset into Mutter's version-2 monitors.xml configuration."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from gi.repository import Gio, GLib


def element(parent, name, text):
    child = ET.SubElement(parent, name)
    child.text = str(text)
    return child


def add_spec(parent, spec):
    node = ET.SubElement(parent, 'monitorspec')
    for key, value in zip(('connector', 'vendor', 'product', 'serial'), spec, strict=True):
        element(node, key, value)


def configuration(layout):
    root = ET.Element('configuration')
    element(root, 'layoutmode', {1: 'logical', 2: 'physical'}[layout['layout_mode']])
    active = set()
    if not layout['logical'] or sum(g['primary'] for g in layout['logical']) != 1:
        raise ValueError('Native layout needs exactly one primary display')
    for group in layout['logical']:
        logical = ET.SubElement(root, 'logicalmonitor')
        for key in ('x', 'y', 'scale'):
            element(logical, key, group[key])
        if group['primary']:
            element(logical, 'primary', 'yes')
        transform = group['transform']
        if not 0 <= transform <= 7:
            raise ValueError('Invalid saved transform')
        if transform:
            node = ET.SubElement(logical, 'transform')
            element(node, 'rotation', ('normal', 'left', 'upside_down', 'right')[transform % 4])
            element(node, 'flipped', 'yes' if transform >= 4 else 'no')
        for monitor in group['monitors']:
            spec = tuple(monitor['spec'])
            if spec in active:
                raise ValueError('Duplicate display in native layout')
            active.add(spec)
            node = ET.SubElement(logical, 'monitor')
            add_spec(node, spec)
            mode = ET.SubElement(node, 'mode')
            element(mode, 'width', monitor['width'])
            element(mode, 'height', monitor['height'])
            element(mode, 'rate', monitor['refresh'])
            if monitor['refresh_mode'] == 'variable':
                element(mode, 'ratemode', 'variable')
            elif monitor['refresh_mode'] != 'fixed':
                raise ValueError('Unknown refresh mode')
            if monitor['interlaced']:
                element(mode, 'flag', 'interlace')
            options = monitor['options']
            if options.get('underscanning'):
                element(node, 'underscanning', 'yes')
            rgb = options.get('rgb-range', 1)
            if rgb != 1:
                element(node, 'rgbrange', {2: 'full', 3: 'limited'}[rgb])
            color = options.get('color-mode', 0)
            if color != 0:
                element(node, 'colormode', {1: 'bt2100', 2: 'sdr-native'}[color])
    connected = {tuple(spec) for spec in layout['connected']}
    leased = {tuple(spec) for spec in layout.get('leased', [])}
    if not active <= connected or not leased <= connected or active & leased:
        raise ValueError('Invalid connected or leased display set')
    for name, specs in (('disabled', connected - active), ('forlease', leased)):
        if specs:
            node = ET.SubElement(root, name)
            for spec in sorted(specs):
                add_spec(node, spec)
    return root


def hardware_key(config):
    return frozenset(tuple(spec.findtext(k, '') for k in ('connector', 'vendor', 'product', 'serial'))
                     for spec in config.findall('.//monitorspec'))


def normalized(node):
    return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(),
            tuple(normalized(child) for child in node))


def merge(existing, layout):
    root = ET.fromstring(existing, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))) \
        if existing else ET.Element('monitors', version='2')
    if root.tag != 'monitors' or root.get('version') != '2':
        raise ValueError('Unsupported monitors.xml format; existing file was not changed')
    desired = configuration(layout)
    matches = [c for c in root.findall('configuration') if hardware_key(c) == hardware_key(desired)]
    if len(matches) == 1 and normalized(matches[0]) == normalized(desired):
        return None
    index = list(root).index(matches[0]) if matches else len(root)
    for config in matches:
        root.remove(config)
    root.insert(index, desired)
    ET.indent(root, space='  ')
    return ET.tostring(root, encoding='utf-8') + b'\n'


def sync(path, layout, backup_dir):
    """Atomic, etag-checked replacement; never overwrite a concurrent GNOME save."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file = Gio.File.new_for_path(str(path))
    for _ in range(3):
        try:
            _, original, etag = file.load_contents(None)
        except GLib.Error as error:
            if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
                raise
            original, etag = b'', None
        updated = merge(original, layout)
        if updated is None:
            return False
        if original:
            backup_dir = Path(backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup = backup_dir / f'monitors-{hashlib.sha256(original).hexdigest()[:16]}.xml'
            if not backup.exists():
                backup.write_bytes(original)
                backup.chmod(0o600)
        try:
            file.replace_contents(updated, etag, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None)
            return True
        except GLib.Error as error:
            if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.WRONG_ETAG):
                raise
    raise ValueError('monitors.xml changed concurrently; sync deferred')

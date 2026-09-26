import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import xml.etree.ElementTree as ET

import backend
import native
from model import snapshot
from test_model import state


class NativeTests(unittest.TestCase):
    def test_encodes_settings_and_disabled_monitor(self):
        layout = snapshot(state())
        xml = native.configuration(layout)
        self.assertEqual(xml.findtext('logicalmonitor/transform/rotation'), 'left')
        self.assertEqual(xml.findtext('logicalmonitor/scale'), '1.5')
        self.assertEqual(xml.findtext('logicalmonitor/monitor/mode/ratemode'), 'variable')
        self.assertEqual(xml.findtext('logicalmonitor/monitor/colormode'), 'bt2100')
        self.assertEqual(xml.findtext('logicalmonitor/monitor/rgbrange'), 'full')
        self.assertEqual(xml.findtext('disabled/monitorspec/connector'), 'HDMI-1')

    def test_merge_replaces_same_hardware_and_preserves_others(self):
        layout = snapshot(state())
        unrelated = copy.deepcopy(layout)
        unrelated['connected'] = [unrelated['connected'][0]]
        original = ET.Element('monitors', version='2')
        original.append(native.configuration(unrelated))
        original.append(native.configuration(layout))
        ET.SubElement(original, 'policy')
        layout['logical'][0]['monitors'][0]['refresh'] = 120.0
        updated = native.merge(ET.tostring(original), layout)
        parsed = ET.fromstring(updated)
        self.assertEqual(len(parsed.findall('configuration')), 2)
        self.assertIsNotNone(parsed.find('policy'))
        self.assertEqual(parsed.findall('configuration')[0].findtext('logicalmonitor/monitor/mode/rate'), '143.851348')
        self.assertIsNone(native.merge(updated, layout))

    def test_atomic_backup_and_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'monitors.xml'
            original = b'<monitors version="2"/>\n'
            path.write_bytes(original)
            layout = snapshot(state())
            self.assertTrue(native.sync(path, layout, Path(directory) / 'backups'))
            stamp = path.stat().st_mtime_ns
            self.assertFalse(native.sync(path, layout, Path(directory) / 'backups'))
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            self.assertEqual(next((Path(directory) / 'backups').iterdir()).read_bytes(), original)

    def test_malformed_or_unknown_xml_is_preserved(self):
        for original in (b'<bad', b'<monitors version="1"/>'):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'monitors.xml'
                path.write_bytes(original)
                with self.assertRaises((ValueError, ET.ParseError)):
                    native.sync(path, snapshot(state()), Path(directory) / 'backups')
                self.assertEqual(path.read_bytes(), original)

    def test_fixed_policy_does_not_follow_last_activated(self):
        a = snapshot(state())
        b = copy.deepcopy(a)
        b['logical'][0]['transform'] = 0
        db = {'last': 'b', 'presets': [{'id': 'a', 'layout': a}, {'id': 'b', 'layout': b}]}
        settings = MagicMock()
        settings.get_boolean.return_value = True
        settings.get_string.side_effect = lambda key: {'startup-policy': 'fixed', 'fixed-preset': 'a'}[key]
        display = MagicMock()
        display.state.return_value = state()
        with patch.object(backend, 'login_settings', return_value=settings), patch.object(native, 'sync') as sync:
            backend.sync_native(display, db)
            self.assertEqual(sync.call_args.args[1]['logical'][0]['transform'], 1)
            settings.get_string.side_effect = lambda key: 'last'
            backend.sync_native(display, db)
            self.assertEqual(sync.call_args.args[1]['logical'][0]['transform'], 0)

    def test_disabled_restore_does_not_write(self):
        settings = MagicMock()
        settings.get_boolean.return_value = False
        with patch.object(backend, 'login_settings', return_value=settings), patch.object(native, 'sync') as sync:
            backend.sync_native(MagicMock(), {})
            sync.assert_not_called()

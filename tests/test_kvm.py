import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import kvm


def device(root, name, vendor='1462', product='3fa4', serial='synthetic-msi-serial'):
    path = root / name
    path.mkdir()
    (path / 'idVendor').write_text(vendor)
    (path / 'idProduct').write_text(product)
    (path / 'serial').write_text(serial)


class KvmTests(unittest.TestCase):
    def test_usb_present_matches_identity_and_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            device(root, '3-8.4')
            device(root, '3-8.5', serial='other')
            self.assertTrue(kvm.usb_present({'vendor': '1462', 'product': '3fa4',
                                             'serial': 'synthetic-msi-serial'}, root))
            self.assertFalse(kvm.usb_present({'vendor': '1462', 'product': '3fa4',
                                              'serial': 'missing'}, root))
            self.assertTrue(kvm.usb_present({'vendor': '1462', 'product': '3fa4'}, root))

    def test_targets_exclude_active_and_include_saved_disconnected(self):
        center = ['DP-3', 'MSI', 'Center', '1']
        side = ['HDMI-1', 'GSM', 'LG HDR 4K', '2']
        preset = {'id': 'center', 'layout': {'logical': [{'monitors': [{'spec': center}]}],
                  'connected': [center, side]}}
        current = preset['layout']
        self.assertEqual(kvm.targets(preset, current, [preset], []),
                         [{'spec': side, 'connector': 'HDMI-1', 'edid': None}])
        config = {'outputs': [{'spec': side, 'edid': 'side-edid', 'code': 15}]}
        result = kvm.redirect_preset(config, preset, current, [preset], [])
        self.assertEqual(result['inputs'][0]['profile']['values'], {'15': 208})
        config['outputs'][0]['spec'] = center
        with self.assertRaises(ValueError):
            kvm.redirect_preset(config, preset, current, [preset], [])

    def test_reject_changed_monitor_edid(self):
        side = ['HDMI-1', 'GSM', 'LG HDR 4K', '2']
        preset = {'layout': {'logical': [], 'connected': [side]}}
        config = {'outputs': [{'spec': side, 'edid': 'old', 'code': 15}]}
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            kvm.redirect_preset(config, preset, preset['layout'], [preset],
                               [{'connector': 'HDMI-1', 'edid': 'new'}])


if __name__ == '__main__':
    unittest.main()

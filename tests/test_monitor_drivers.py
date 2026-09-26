"""Driver boundaries: unchanged persisted values, dispatch and hardware safeguards."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import inputs
import input_actions
import monitor_drivers as drivers
import msi


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.lg = ['HDMI-1', 'GSM', 'LG HDR 4K', 'synthetic-lg']
        self.msi = ['DP-1', 'MSI', 'MSI MAG323UPF', 'synthetic-msi']
        self.other = ['DP-2', 'OTHER', 'Example', 'synthetic-other']

    def test_registry_fallback_and_no_model_overreach(self):
        self.assertEqual(drivers.select(self.lg).id, 'lg-hdr-4k')
        self.assertEqual(drivers.select(self.msi).channel, 'usb-hid')
        self.assertEqual(drivers.select(self.other).id, 'generic-ddc')
        self.assertEqual(drivers.select(['DP-1', 'MSI', 'Another MSI model', 'x']).id, 'generic-ddc')

    def test_ambiguous_match_is_rejected(self):
        with patch.object(drivers, 'DRIVERS', (drivers.select(self.lg), drivers.select(self.lg))):
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                drivers.select(self.lg)

    def test_legacy_cache_values_survive_refresh_and_options(self):
        entry = {'codes': [15, 16, 17, 18], 'usb_c': True, 'future': 'keep'}
        options = drivers.options(self.lg, entry)
        self.assertEqual(options[0]['key'], 'usb_c')
        self.assertTrue(options[0]['value'])
        updated = drivers.update_options(self.lg, entry, {'usb_c': False})
        self.assertEqual(updated, {**entry, 'usb_c': False})
        self.assertTrue(entry['usb_c'])
        self.assertNotIn(16, [c['code'] for c in drivers.select(self.lg).choices(updated)])
        self.assertEqual(drivers.options(self.other, {}), [])

    def test_options_reject_unknown_keys_types_and_wrong_driver(self):
        for changes in ({'usb_c': 'true'}, {'usb_c': 1}, {'other': True}, {}):
            with self.assertRaises(ValueError):
                drivers.update_options(self.lg, {}, changes)
        with self.assertRaises(ValueError):
            drivers.update_options(self.msi, {}, {'usb_c': True})

    def test_new_driver_options_need_no_frontend_model_branch(self):
        class Example(drivers.GENERIC.__class__):
            manual_options = ({'key': 'custom', 'type': 'boolean', 'label': 'Example option',
                               'tooltip': 'Example', 'default': False},)
        with patch.object(drivers, 'DRIVERS', (Example(),)):
            changed = drivers.update_options(self.other, {}, {'custom': True})
            self.assertTrue(drivers.options(self.other, changed)[0]['value'])

    def test_msi_discovery_uses_usb_and_preserves_cache(self):
        target = {'spec': self.msi, 'connector': 'DP-1', 'edid': 'test-edid'}
        cache = {inputs.identity(self.msi): {'future': 'keep'}}
        with patch.object(msi, 'devices', return_value=[{'serial': 'test'}]), \
                patch.object(msi, 'open_device', return_value=9), patch.object(msi, 'query', return_value=3), \
                patch('monitor_drivers.msi_mag.os.close') as close, \
                patch('monitor_drivers.generic_ddc.subprocess.run') as ddc:
            self.assertEqual(inputs.refresh([target], [], cache), (1, []))
        ddc.assert_not_called()
        close.assert_called_once_with(9)
        self.assertEqual(cache[inputs.identity(self.msi)]['future'], 'keep')
        self.assertEqual(drivers.select(self.msi).choices({})[1], {'code': 16, 'label': 'USB-C'})

    def test_msi_route_preserves_profile_and_layout_eligibility(self):
        current = {'connected': [self.msi], 'logical': [{'monitors': [{'spec': self.msi}]}]}
        output = {'spec': self.msi, 'edid': 'test-edid', 'code': 15}
        devices = [{'connector': 'DP-1', 'edid': 'test-edid', 'bus': 4}]
        with patch.object(msi, 'devices', return_value=[{'serial': 'test'}]) as controls:
            request = input_actions.route(output, current, [], devices, {})
            self.assertEqual(request['inputs'][0]['profile'], {'transport': 'msi-usb', 'usb': {'serial': 'test'}})
            controls.reset_mock()
            with self.assertRaisesRegex(ValueError, 'disabled'):
                input_actions.route(output, {**current, 'logical': []}, [], devices, {})
            controls.assert_not_called()

    def test_no_fallback_after_specific_driver_failure(self):
        with patch.object(msi, 'devices', return_value=[]), \
                patch('monitor_drivers.generic_ddc.subprocess.run') as ddc:
            target = {'spec': self.msi, 'connector': 'DP-1', 'edid': 'test'}
            cache = {inputs.identity(self.msi): {'codes': [17]}}
            updated, warnings = inputs.refresh([target], [], cache)
            self.assertEqual(updated, 0)
            self.assertEqual(len(warnings), 1)
            self.assertEqual(cache[inputs.identity(self.msi)]['codes'], [17])
            ddc.assert_not_called()
        self.assertFalse(drivers.select(self.lg).allows_transport('standard'))
        with self.assertRaises(ValueError):
            drivers.transport('untrusted-plugin-path')

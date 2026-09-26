import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import inputs
import kvm

REPORT = '''Feature: 14 (Color)
    05: 6500 K
Feature: 60 (Input Source)
    Values:
        11: HDMI-1
        12: HDMI-2
        0f: DisplayPort-1
        10: DisplayPort-2
Feature: D6 (Power)
    01: On
'''


class InputTests(unittest.TestCase):
    def setUp(self):
        self.spec = ['HDMI-1', 'GSM', 'LG HDR 4K', 'unique']
        self.target = {'spec': self.spec, 'connector': 'HDMI-1', 'edid': 'edid'}
        self.devices = [{'connector': 'HDMI-1', 'edid': 'edid', 'bus': 3}]

    def test_parse_only_input_values(self):
        self.assertEqual(inputs.parse_capabilities(REPORT), [15, 16, 17, 18])
        with self.assertRaises(ValueError):
            inputs.parse_capabilities('Feature: 60 (Input Source)\nFeature: 10 (Brightness)')

    def test_refresh_retains_profile_and_uses_read_only_uncached_query(self):
        key = inputs.identity(self.spec)
        cache = {key: {'usb_c': True}}
        with patch('inputs.subprocess.run', return_value=subprocess.CompletedProcess([], 0, REPORT, '')) as run:
            self.assertEqual(inputs.refresh([self.target], self.devices, cache), (1, []))
        self.assertIn('--disable-capabilities-cache', run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-1], 'capabilities')
        self.assertTrue(cache[key]['usb_c'])
        self.assertEqual(cache[key]['codes'], [15, 16, 17, 18])

    def test_failed_refresh_retains_cache(self):
        cache = {'existing': {'codes': [17]}}
        with patch('inputs.subprocess.run', side_effect=subprocess.TimeoutExpired('ddcutil', 20)):
            count, warnings = inputs.refresh([self.target], self.devices, cache)
        self.assertEqual(count, 0)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(cache, {'existing': {'codes': [17]}})

    def test_lg_usb_c_is_explicit_and_routes_alternate_command(self):
        cache = {inputs.identity(self.spec): {'usb_c': True, 'codes': [15, 16, 17, 18]}}
        self.assertEqual(next(c['label'] for c in inputs.choices(self.spec, cache) if c['code'] == 16), 'USB-C')
        preset = {'layout': {'logical': [], 'connected': [self.spec]}}
        config = {'outputs': [{**self.target, 'code': 16}]}
        with self.assertRaises(ValueError):
            kvm.redirect_preset(config, preset, preset['layout'], [preset], self.devices)
        result = kvm.redirect_preset(config, preset, preset['layout'], [preset], self.devices, cache)
        self.assertEqual(result['inputs'][0]['profile'], {'transport': 'lg-f4', 'values': {'16': 209}})

    def test_cable_move_keeps_identity_and_uses_new_connector(self):
        moved = ['HDMI-2', *self.spec[1:]]
        preset = {'layout': {'logical': [], 'connected': [self.spec]}}
        current = {'logical': [], 'connected': [moved]}
        devices = [{'connector': 'HDMI-2', 'edid': 'edid', 'bus': 9}]
        self.assertEqual(inputs.identity(self.spec), inputs.identity(moved))
        targets = kvm.targets(preset, current, [preset], devices)
        self.assertEqual(len(targets), 1)
        config = {'outputs': [{**self.target, 'code': 15}]}
        result = kvm.redirect_preset(config, preset, current, [preset], devices)
        self.assertEqual(result['inputs'][0]['connector'], 'HDMI-2')

    def test_generic_monitor_uses_advertised_non_default_inputs(self):
        spec = ['DP-1', 'OTHER', 'Other monitor', '42']
        cache = {inputs.identity(spec): {'codes': [3, 27]}}
        self.assertEqual(inputs.choices(spec, cache), [{'code': 3, 'label': 'DVI 1'}, {'code': 27, 'label': 'USB-C'}])

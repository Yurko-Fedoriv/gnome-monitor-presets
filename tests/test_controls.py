"""No hardware writes: validate DDC parsing, identity checks and write limits."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import controls


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.spec = ['HDMI-1', 'GSM', 'LG HDR 4K', 'unique']
        self.request = {'spec': self.spec, 'edid': 'hash'}
        self.current = {'logical': [{'monitors': [{'spec': self.spec}]}]}
        self.displays = [{'connector': 'HDMI-1', 'edid': 'hash', 'bus': 3}]

    def execute(self, **kwargs):
        return controls.execute({**self.request, **kwargs}, self.current, self.displays, write=True)

    def test_read_all_three_monitor_response_formats(self):
        for brightness, volume, mute in [(80, 49, '01'), (80, 100, '01'), (70, 28, '02')]:
            with patch.object(controls, 'command', side_effect=[f'VCP 10 C {brightness} 100',
                    f'VCP 62 C {volume} 100', f'VCP 8D SNC x{mute}']):
                result = controls.execute(self.request, self.current, self.displays)['controls']
                self.assertEqual(result['volume']['value'], volume)
                self.assertEqual(result['mute']['value'], mute == '01')

    def test_unsupported_or_malformed_controls_hidden_independently(self):
        with patch.object(controls, 'command', side_effect=['VCP 10 C 10 100', 'VCP 62 ERR', 'VCP 8D SNC x0101']):
            result = controls.execute(self.request, self.current, self.displays)
            self.assertEqual(list(result['controls']), ['brightness'])
            self.assertEqual(set(result['unavailable']), {'volume', 'mute'})

    def test_reject_stale_or_ambiguous_monitor_before_io(self):
        with patch.object(controls, 'command') as command:
            for displays in ([], [{**self.displays[0], 'edid': 'different'}], self.displays * 2):
                with self.assertRaises(ValueError):
                    controls.execute(self.request, self.current, displays)
            with self.assertRaises(ValueError):
                controls.execute(self.request, {'logical': []}, self.displays)
            command.assert_not_called()

    def test_validate_raw_hardware_range_not_assumed_percentage(self):
        with patch.object(controls, 'command', side_effect=['VCP 10 C 150 255', '', 'VCP 10 C 200 255']) as command:
            self.assertEqual(self.execute(feature='brightness', value=200)['control']['value'], 200)
            self.assertEqual(command.call_args_list[1].args, (3, 'setvcp', '10', '200'))
        for value in (-1, 101, True, '50'):
            with patch.object(controls, 'command', return_value='VCP 62 C 20 100') as command:
                with self.assertRaises(ValueError): self.execute(feature='volume', value=value)
                self.assertEqual(command.call_count, 1)

    def test_mute_only_writes_audio_values_and_verifies(self):
        for muted, raw in [(True, '1'), (False, '2')]:
            with patch.object(controls, 'command', side_effect=['VCP 8D SNC x02', '', f'VCP 8D SNC x0{raw}']) as command:
                self.assertEqual(self.execute(feature='mute', value=muted)['control']['value'], muted)
                self.assertEqual(command.call_args_list[1].args, (3, 'setvcp', '8D', raw))
        with patch.object(controls, 'command') as command:
            with self.assertRaises(ValueError): self.execute(feature='input', value=17)
            command.assert_not_called()

    def test_unsupported_read_prevents_write(self):
        with patch.object(controls, 'command', return_value='VCP 62 ERR') as command:
            with self.assertRaises(ValueError): self.execute(feature='volume', value=10)
            self.assertEqual(command.call_count, 1)

class CapabilityCacheTests(unittest.TestCase):
    def setUp(self):
        import inputs
        self.spec = ['HDMI-1', 'GSM', 'LG HDR 4K', 'one']
        self.monitor = {'spec': self.spec, 'connector': 'HDMI-1', 'edid': 'edid'}
        self.key = inputs.identity(self.spec)
        self.current = {'logical': [{'monitors': [{'spec': self.spec}]}]}
        self.devices = [{'connector': 'HDMI-1', 'edid': 'edid', 'bus': 3}]
        self.cache = {self.key: {'codes': [15, 17], 'usb_c': True, 'controls_edid': 'edid',
                              'controls': {'brightness': {'value': 80, 'maximum': 100},
                                           'volume': {'value': 49, 'maximum': 100}}}}

    def test_discovery_preserves_manual_settings_and_retains_transient_failures(self):
        import subprocess
        with patch.object(controls, 'read', side_effect=[{'value': 70, 'maximum': 100},
                subprocess.TimeoutExpired('ddcutil', 6), controls.UnsupportedControl('Unsupported')]):
            warnings = controls.refresh([self.monitor], self.current, self.devices, self.cache)
        entry = self.cache[self.key]
        self.assertTrue(entry['usb_c'])
        self.assertEqual(entry['codes'], [15, 17])
        self.assertEqual(entry['controls']['brightness']['value'], 70)
        self.assertEqual(entry['controls']['volume']['value'], 49)
        self.assertNotIn('mute', entry['controls'])
        self.assertTrue(entry['controls_updated'])
        self.assertEqual(len(warnings), 1)

    def test_cached_capabilities_survive_cable_move_but_reject_changed_edid(self):
        import inputs
        moved = ['DP-1', *self.spec[1:]]
        with patch.object(controls, 'command') as command:
            self.assertEqual(controls.cached(moved, 'edid', self.cache)['volume']['value'], 49)
            self.assertEqual(controls.cached(moved, 'different', self.cache), {})
            described = inputs.describe({**self.monitor, 'spec': moved}, self.cache)
            self.assertEqual(described['controls']['brightness']['value'], 80)
            command.assert_not_called()

    def test_backend_cached_reads_do_not_probe_and_writes_update_persistent_values(self):
        import argparse
        import backend
        import json
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary, patch.object(backend, 'ROOT', Path(temporary)):
            backend.write_json(backend.ROOT / 'input-capabilities.json', self.cache)
            args = argparse.Namespace(command='monitor-controls', value=json.dumps(self.monitor))
            with patch.object(controls, 'command') as command:
                self.assertEqual(backend.execute(args, None, {})['controls']['volume']['value'], 49)
                command.assert_not_called()
            args.command = 'set-monitor-control'
            args.value = json.dumps({**self.monitor, 'feature': 'volume', 'value': 65})
            display = Mock(capture=lambda: self.current)
            with patch.object(backend, 'drm_displays', return_value=self.devices), \
                    patch.object(controls, 'command', side_effect=['VCP 62 C 49 100', '', 'VCP 62 C 65 100']):
                backend.execute(args, display, {})
            saved = backend.read_json(backend.ROOT / 'input-capabilities.json')[self.key]
            self.assertEqual(saved['controls']['volume']['value'], 65)
            self.assertTrue(saved['usb_c'])
            self.assertEqual(saved['controls']['brightness']['value'], 80)


if __name__ == '__main__':
    unittest.main()

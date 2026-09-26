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


if __name__ == '__main__':
    unittest.main()

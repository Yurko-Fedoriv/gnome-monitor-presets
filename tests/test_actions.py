import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import input_actions
import msi


class Settings:
    def __init__(self, **values): self.values = values
    def get_boolean(self, key): return self.values.get(key, False)
    def set_boolean(self, key, value): self.values[key] = value
    def get_string(self, key): return self.values.get(key, '[]' if key in ('monitor-actions', 'input-shortcuts') else '{}')
    def set_string(self, key, value): self.values[key] = value


class ActionTests(unittest.TestCase):
    def test_migrate_kvm_once_preserving_destinations(self):
        old = {'usb': {'serial': 'one'}, 'preset': 'center', 'outputs': [{'code': 15, 'spec': ['HDMI-1', 'GSM', 'LG', 'one'], 'edid': 'old'}]}
        settings = Settings(**{'kvm-config': json.dumps(old)})
        actions = input_actions.load(settings)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['outputs'], old['outputs'])
        self.assertEqual(actions[0]['preset'], 'center')
        self.assertEqual(actions[0]['triggers'], [{'type': 'kvm'}])
        self.assertEqual(input_actions.load(settings), actions)
        settings.set_string('monitor-actions', '[]')
        self.assertEqual(input_actions.load(settings), []) # Deletion does not resurrect old action.

    def test_input_route_allows_enabled_monitor_and_guards_identity(self):
        spec = ['HDMI-1', 'GSM', 'LG HDR 4K', 'one']
        current = {'connected': [spec], 'logical': [{'monitors': [{'spec': spec}]}]}
        output = {'spec': spec, 'edid': 'edid', 'code': 15}
        devices = [{'connector': 'HDMI-1', 'edid': 'edid', 'bus': 3}]
        request = input_actions.route(output, current, [], devices, {})
        self.assertEqual(request['inputs'][0]['profile']['transport'], 'lg-f4')
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            input_actions.route(output, current, [], [{'connector': 'HDMI-1', 'edid': 'other'}], {})
        # EDID remains visible while the disabled LG is showing another computer.
        # Reject before any DDC operation can spend seconds retrying that input.
        with self.assertRaisesRegex(ValueError, 'monitor is disabled'):
            input_actions.route(output, {**current, 'logical': []}, [], devices, {})

    def test_msi_same_input_sends_no_write(self):
        with patch.object(msi, 'open_device', return_value=9), patch.object(msi, 'query', return_value=2), \
                patch.object(msi, 'exchange') as exchange, patch.object(msi.os, 'close'):
            msi.switch_input({'serial': 'one'}, 15)
            exchange.assert_not_called()

    def test_msi_type_c_command(self):
        with patch.object(msi, 'open_device', return_value=9), patch.object(msi, 'query', return_value=2), \
                patch.object(msi, 'exchange', return_value=b'') as exchange, patch.object(msi.os, 'close'):
            msi.switch_input({'serial': 'one'}, 16)
            self.assertEqual(exchange.call_args.args[1], b'5b00500003')

    def test_msi_disconnect_after_input_request_is_expected(self):
        with patch.object(msi, 'open_device', return_value=9), patch.object(msi, 'query', return_value=2), \
                patch.object(msi, 'exchange', side_effect=TimeoutError), patch.object(msi, 'devices', return_value=[]), \
                patch.object(msi.os, 'close'):
            msi.switch_input({'serial': 'one'}, 16)

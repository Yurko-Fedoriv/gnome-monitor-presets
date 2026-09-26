import argparse
import copy
from pathlib import Path
import sys
import tempfile
import time
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extension"))
import backend


class FakeDisplay:
    def __init__(self):
        self.current = {"name": "before"}
        self.fail = False
        self.session = "compositor-one"

    def session_key(self):
        return self.session

    def capture(self):
        return copy.deepcopy(self.current)

    def apply(self, target, verify=False):
        if verify:
            return
        if self.fail and target["name"] == "after":
            raise ValueError("Apply failed")
        self.current = copy.deepcopy(target)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(backend, "ROOT", Path(self.temp.name))
        self.root_patch.start()
        self.spawn_patch = patch.object(backend.subprocess, "Popen")
        self.spawn_patch.start()
        self.display = FakeDisplay()
        self.db = {"version": 1, "presets": []}

    def tearDown(self):
        self.spawn_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    def test_revert_preserves_previous_and_clears_pending(self):
        change = backend.activate(self.display, self.db, {"name": "after"})
        self.assertEqual(self.display.current["name"], "after")
        backend.rollback(self.display, self.db, change["token"])
        self.assertEqual(self.display.current["name"], "before")
        self.assertFalse(backend.pending_path().exists())

    def test_failed_apply_rolls_back(self):
        self.display.fail = True
        with self.assertRaisesRegex(ValueError, "Apply failed"):
            backend.activate(self.display, self.db, {"name": "after"})
        self.assertEqual(self.display.current["name"], "before")
        self.assertFalse(backend.pending_path().exists())

    def test_double_activation_cannot_overwrite_recovery(self):
        backend.activate(self.display, self.db, {"name": "after"})
        with self.assertRaisesRegex(ValueError, "pending"):
            backend.activate(self.display, self.db, {"name": "third"})
        self.assertEqual(backend.read_json(backend.pending_path())["before"]["name"], "before")

    def test_old_watchdog_does_not_revert_new_transaction(self):
        backend.activate(self.display, self.db, {"name": "after"})
        backend.rollback(self.display, self.db, "wrong-token")
        self.assertEqual(self.display.current["name"], "after")

    def test_expired_confirmation_reverts_instead_of_committing(self):
        change = backend.activate(self.display, self.db, {"name": "after"})
        pending = backend.read_json(backend.pending_path())
        pending["deadline"] = time.time() - 1
        backend.write_json(backend.pending_path(), pending)
        with self.assertRaisesRegex(ValueError, "expired"):
            backend.execute(argparse.Namespace(command="confirm", value=change["token"]), self.display, self.db)
        self.assertEqual(self.display.current["name"], "before")

    def test_confirm_keeps_undo_snapshot(self):
        change = backend.activate(self.display, self.db, {"name": "after"})
        backend.execute(argparse.Namespace(command="confirm", value=change["token"]), self.display, self.db)
        self.assertEqual(self.db["previous"]["name"], "before")
        self.assertFalse(backend.pending_path().exists())

    def test_login_restores_last_only_once(self):
        self.db["presets"] = [{"id": "a", "layout": {"name": "after"}}]
        self.db["last"] = "a"
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.temp.name, "XDG_SESSION_ID": "test"}), \
                patch.object(backend, "signature", side_effect=lambda layout: layout["name"]):
            args = argparse.Namespace(command="startup", value="last")
            backend.execute(args, self.display, self.db)
            self.assertEqual(self.display.current["name"], "after")
            self.display.current = {"name": "changed-by-user"}
            backend.execute(args, self.display, self.db)
            self.assertEqual(self.display.current["name"], "changed-by-user")

    def test_fixed_login_does_not_follow_last(self):
        self.db["presets"] = [{"id": "a", "layout": {"name": "fixed"}},
                              {"id": "b", "layout": {"name": "last"}}]
        self.db["last"] = "b"
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.temp.name, "XDG_SESSION_ID": "test"}), \
                patch.object(backend, "signature", side_effect=lambda layout: layout["name"]):
            backend.execute(argparse.Namespace(command="startup", value="a"), self.display, self.db)
        self.assertEqual(self.display.current["name"], "fixed")

    def test_new_compositor_restores_with_same_runtime_and_no_session_env(self):
        self.db.update(last="a", presets=[{"id": "a", "layout": {"name": "after"}}])
        # Reproduce the old stale marker as well as the persistent runtime dir.
        (Path(self.temp.name) / 'monitor-presets-started-1').touch()
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.temp.name, "XDG_SESSION_ID": ""}), \
                patch.object(backend, "signature", side_effect=lambda layout: layout["name"]):
            args = argparse.Namespace(command="startup", value="last")
            backend.execute(args, self.display, self.db)
            self.display.current = {"name": "before"}
            self.display.session = "compositor-two"
            result = backend.execute(args, self.display, self.db)
            self.assertEqual(result['message'], 'Login layout restored')
            self.assertEqual(self.display.current["name"], "after")

    def test_failed_login_restore_does_not_mark_session_complete(self):
        self.db.update(last="a", presets=[{"id": "a", "layout": {"name": "after"}}])
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.temp.name}), \
                patch.object(backend, "signature", side_effect=lambda layout: layout["name"]):
            self.display.fail = True
            with self.assertRaisesRegex(ValueError, "Apply failed"):
                backend.execute(argparse.Namespace(command="startup", value="last"), self.display, self.db)
            self.assertFalse((Path(self.temp.name) / 'monitor-presets-startup.json').exists())
            self.display.fail = False
            backend.execute(argparse.Namespace(command="startup", value="last"), self.display, self.db)
            self.assertEqual(self.display.current["name"], "after")

    def test_ddc_rediscovers_bus_from_edid(self):
        preset = {"claim_inputs": True,
                  "inputs": [{"connector": "HDMI-1", "edid": "fingerprint", "code": 17}]}
        with patch.object(backend, "drm_displays", return_value=[{"edid": "fingerprint", "bus": 9}]), \
                patch.object(backend, "read_input", side_effect=[18, 17]), \
                patch.object(backend.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(backend.claim_inputs(preset), [])
            self.assertEqual(run.call_args.args[0], ["ddcutil", "--bus", "9", "--noverify", "setvcp", "60", "0x11"])

    def test_removed_input_actions_cannot_be_called(self):
        for command in ('claim', 'inputs', 'detect-inputs', 'kvm-route'):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'Unknown command'):
                backend.execute(argparse.Namespace(command=command), self.display, self.db)

    def test_kvm_routes_before_immediate_layout_and_skips_returned_usb(self):
        import json, kvm, input_actions
        from unittest.mock import Mock
        self.db['presets'] = [{'id': 'a', 'layout': {'name': 'after'}}]
        action = {'id': 'action', 'preset': 'a', 'outputs': [{}], 'triggers': [{'type': 'kvm'}]}
        settings = Mock()
        settings.get_boolean.return_value = True
        settings.get_double.return_value = 0
        settings.get_string.return_value = json.dumps({'usb': {'vendor': 'x'}})
        events = []
        apply = self.display.apply
        def record_apply(target, verify=False):
            events.append('verify' if verify else 'apply')
            return apply(target, verify)
        with patch.object(backend, 'login_settings', return_value=settings), \
                patch.object(input_actions, 'load', return_value=[action]), \
                patch.object(input_actions, 'route', return_value={'inputs': []}), \
                patch.object(kvm, 'usb_present', return_value=False) as present, \
                patch.object(backend, 'drm_displays', return_value=[]), \
                patch.object(backend, 'claim_inputs', side_effect=lambda *a, **kw: events.append('inputs') or ['DDC failed']), \
                patch.object(self.display, 'apply', side_effect=record_apply):
            result = backend.execute(argparse.Namespace(command='kvm-disconnect'), self.display, self.db)
            self.assertEqual(result['skipped_monitors'], ['DDC failed'])
            self.assertNotIn('warnings', result)
            self.assertLess(events.index('inputs'), events.index('apply'))
            self.assertEqual(self.db['last'], 'a')
            self.assertFalse(backend.pending_path().exists())
            events.clear()
            present.return_value = True
            self.assertIn('skipped', backend.execute(argparse.Namespace(command='kvm-disconnect'), self.display, self.db))
            self.assertEqual(events, [])

    def test_unavailable_preset_does_not_prevent_independent_redirects(self):
        import input_actions
        from unittest.mock import Mock
        self.db['presets'] = [{'id': 'a', 'layout': {'name': 'after'}}]
        action = {'id': 'action', 'preset': 'a', 'outputs': [{}]}
        with patch.object(backend, 'login_settings', return_value=Mock()), \
                patch.object(self.display, 'apply', side_effect=ValueError('Missing monitor')), \
                patch.object(input_actions, 'route', return_value={'inputs': []}), \
                patch.object(backend, 'drm_displays', return_value=[]), \
                patch.object(backend, 'claim_inputs', return_value=[]) as claim:
            result = backend.perform_action(action, self.display, self.db, suppress=False)
            self.assertEqual(result['skipped_monitors'], ['Missing monitor'])
            claim.assert_called_once()

    def test_action_only_redirects_and_does_not_apply_layout(self):
        import input_actions
        from unittest.mock import Mock
        action = {'id': 'action', 'preset': None, 'outputs': [{}, {}]}
        with patch.object(backend, 'login_settings', return_value=Mock()), \
                patch.object(self.display, 'apply') as apply, \
                patch.object(input_actions, 'route', side_effect=[ValueError('Disconnected'), {'inputs': []}]), \
                patch.object(backend, 'drm_displays', return_value=[]), \
                patch.object(backend, 'claim_inputs', return_value=[]) as claim:
            result = backend.perform_action(action, self.display, self.db, suppress=False)
            self.assertEqual(result['skipped_monitors'], ['Disconnected'])
            self.assertNotIn('warnings', result)
            apply.assert_not_called()
            claim.assert_called_once()

    def test_action_guard_blocks_overlapping_queued_invocation(self):
        backend.write_json(backend.ROOT / 'last-action.json', {'finished': time.time() + 1})
        with patch.object(self.display, 'apply') as apply:
            result = backend.perform_action({'id': 'x'}, self.display, self.db, suppress=False)
            self.assertEqual(result['skipped'], 'overlapping action')
            apply.assert_not_called()

    def test_action_batches_all_routes_before_dispatch(self):
        import input_actions
        from unittest.mock import Mock
        outputs = [{'connector': 'HDMI-1'}, {'connector': 'DP-3'}]
        with patch.object(backend, 'login_settings', return_value=Mock()), \
                patch.object(backend, 'drm_displays', return_value=[]), \
                patch.object(input_actions, 'route', side_effect=[{'inputs': [o]} for o in outputs]), \
                patch.object(backend, 'claim_inputs', return_value=[]) as claim:
            backend.perform_action({'id': 'both', 'outputs': outputs}, self.display, self.db, suppress=False)
        claim.assert_called_once()
        self.assertEqual(claim.call_args.args[0]['inputs'], outputs)

    def test_preset_activation_ignores_legacy_input_settings(self):
        self.db['presets'] = [{'id': 'a', 'layout': {'name': 'after'},
                              'claim_inputs': True, 'inputs': [1]}]
        with patch.object(backend, 'claim_inputs') as claim:
            backend.activate(self.display, self.db, {'name': 'after'}, 'a', require_confirmation=False)
            claim.assert_not_called()

    def test_manual_claim_bypasses_automatic_switch_setting(self):
        preset = {"claim_inputs": False,
                  "inputs": [{"connector": "HDMI-1", "edid": "unique", "code": 18}]}
        with patch.object(backend, "drm_displays", return_value=[{"edid": "unique", "bus": 3}]), \
                patch.object(backend, "read_input", side_effect=[17, 18]), \
                patch.object(backend.subprocess, "run") as run:
            run.return_value.returncode = 0
            backend.claim_inputs(preset)
            run.assert_not_called()
            self.assertEqual(backend.claim_inputs(preset, manual=True), [])
            run.assert_called_once()

    def test_already_selected_input_never_receives_write(self):
        preset = {"inputs": [{"connector": "HDMI-1", "edid": "unique", "code": 18}]}
        with patch.object(backend, "drm_displays", return_value=[{"edid": "unique", "bus": 3}]), \
                patch.object(backend, "read_input", return_value=18), \
                patch.object(backend.subprocess, "run") as run:
            self.assertEqual(backend.claim_inputs(preset, manual=True), [])
            run.assert_not_called()
        report = backend.read_json(backend.ROOT / "last-input-check.json")
        self.assertEqual(report["results"][0]["status"], "already-selected")

    def test_failed_read_still_allows_input_write(self):
        preset = {"inputs": [{"connector": "HDMI-1", "edid": "unique", "code": 18}]}
        with patch.object(backend, "drm_displays", return_value=[{"edid": "unique", "bus": 3}]), \
                patch.object(backend, "read_input", side_effect=[ValueError("read unsupported"), 18]), \
                patch.object(backend.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(backend.claim_inputs(preset, manual=True), [])
            run.assert_called_once()

    def test_lg_standard_input_writes_are_blocked(self):
        preset = {'claim_inputs': True,
                  'layout': {'logical': [{'monitors': [{'spec': ['HDMI-1', 'GSM', 'LG HDR 4K', 'serial']}]}]},
                  'inputs': [{'connector': 'HDMI-1', 'edid': 'unique', 'code': 18}]}
        for manual in (False, True):
            with self.subTest(manual=manual), \
                    patch.object(backend, 'drm_displays', return_value=[{'edid': 'unique', 'bus': 3}]), \
                    patch.object(backend, 'read_input', return_value=18) as read, \
                    patch.object(backend.subprocess, 'run') as run:
                run.return_value.returncode = 0
                self.assertIn('LG lockups', backend.claim_inputs(preset, manual=manual)[0])
                run.assert_not_called()
                read.assert_not_called()
                report = backend.read_json(backend.ROOT / 'last-input-check.json')['results'][0]
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['transport'], 'blocked')

    def test_lg_alternate_transport_uses_explicit_values_without_reads(self):
        preset = {'inputs': [{'connector': 'HDMI-1', 'edid': 'unique', 'code': 18}]}
        backend.write_json(backend.ROOT / 'input-transports.json', {
            'unique': {'transport': 'lg-f4', 'values': {'18': 145, '15': 208}}})
        with patch.object(backend, 'drm_displays', return_value=[{'edid': 'unique', 'bus': 9}]), \
                patch.object(backend, 'read_input') as read, \
                patch.object(backend.subprocess, 'run') as run:
            run.return_value.returncode = 0
            for code, value in ((18, '0x91'), (15, '0xd0')):
                preset['inputs'][0]['code'] = code
                self.assertEqual(backend.claim_inputs(preset, manual=True), [])
                self.assertEqual(run.call_args.args[0], ['ddcutil', '--bus', '9', '--noverify',
                    '--mccs', '2.2', '--i2c-source-addr=0x50', '--maxtries', '1,.,.', 'setvcp', 'f4', value])
            read.assert_not_called()
            self.assertEqual(run.call_count, 2)
            run.reset_mock()
            preset['inputs'][0]['code'] = 17
            self.assertIn('No tested LG input command', backend.claim_inputs(preset, manual=True)[0])
            run.assert_not_called()
            preset['inputs'][0]['code'] = 18
            run.return_value.returncode = 1
            run.return_value.stderr = 'ENXIO'
            self.assertTrue(backend.claim_inputs(preset, manual=True))
            run.assert_called_once()  # No standard-input fallback or retry.

    def test_independent_inputs_progress_together_and_merge_failures(self):
        import threading
        import subprocess
        import msi
        ready = threading.Barrier(3, timeout=2)
        mappings = [
            {'connector': f'HDMI-{i}', 'edid': str(i), 'code': 15,
             'profile': {'transport': 'lg-f4', 'values': {'15': 208}}}
            for i in (1, 2)]
        mappings.append({'connector': 'DP-3', 'edid': 'msi', 'code': 16,
                         'profile': {'transport': 'msi-usb', 'usb': {'serial': 'msi'}}})
        devices = [{'edid': m['edid'], 'bus': i} for i, m in enumerate(mappings)]
        def send(command, **kwargs):
            ready.wait()  # Fails if an unreachable LG blocks the other monitors.
            return subprocess.CompletedProcess(command, 1, '', 'ENXIO')
        def switch(*args):
            ready.wait()
        with patch.object(backend, 'drm_displays', return_value=devices), \
                patch.object(backend.subprocess, 'run', side_effect=send), \
                patch.object(msi, 'switch_input', side_effect=switch):
            errors = backend.claim_inputs({'inputs': mappings}, manual=True)
        self.assertEqual(len(errors), 2)
        report = backend.read_json(backend.ROOT / 'last-input-check.json')['results']
        self.assertEqual([r['status'] for r in report], ['failed', 'failed', 'request-sent'])

    def test_same_bus_commands_share_one_worker(self):
        import threading
        ready = threading.Barrier(2, timeout=2)
        groups = []
        mappings = [{'connector': str(i), 'edid': str(i), 'code': 15} for i in range(3)]
        devices = [{'edid': str(i), 'bus': 3 if i < 2 else 4} for i in range(3)]
        def send(preset):
            groups.append([m['edid'] for m in preset['inputs']])
            ready.wait()
            return [], []
        with patch.object(backend, 'drm_displays', return_value=devices), \
                patch.object(backend, '_claim_inputs', side_effect=send):
            backend.claim_inputs({'inputs': mappings}, manual=True)
        self.assertCountEqual(groups, [['0', '1'], ['2']])

    def test_write_failure_is_logged_and_identifies_monitor(self):
        preset = {"inputs": [{"connector": "HDMI-1", "edid": "unique", "code": 18}]}
        with patch.object(backend, "drm_displays", return_value=[{"edid": "unique", "bus": 3}]), \
                patch.object(backend, "read_input", side_effect=ValueError("ENXIO")), \
                patch.object(backend.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "Full diagnostic: ENXIO"
            errors = backend.claim_inputs(preset, manual=True)
            self.assertIn("HDMI-1", errors[0])
            self.assertIn("Wake", errors[0])
        self.assertEqual(backend.read_json(backend.ROOT / "last-input-check.json")["results"][0]["error"],
                         "Full diagnostic: ENXIO")

    def test_login_skips_matching_layout(self):
        self.db["presets"] = [{"id": "a", "layout": {"name": "before"}}]
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.temp.name, "XDG_SESSION_ID": "test"}), \
                patch.object(backend, "signature", side_effect=lambda layout: layout["name"]), \
                patch.object(self.display, "apply") as apply:
            result = backend.execute(argparse.Namespace(command="startup", value="a"), self.display, self.db)
            self.assertTrue(result["skipped"])
            apply.assert_not_called()

    def test_immediate_apply_commits_and_keeps_undo(self):
        self.db["presets"] = [{"id": "a", "layout": {"name": "after"}}]
        result = backend.activate(self.display, self.db, {"name": "after"}, "a", require_confirmation=False)
        self.assertTrue(result["ok"])
        self.assertNotIn("token", result)
        self.assertEqual(self.db["last"], "a")
        self.assertEqual(self.db["previous"], {"name": "before"})
        self.assertFalse(backend.pending_path().exists())

    def test_failed_immediate_apply_still_restores_original(self):
        self.display.fail = True
        with self.assertRaisesRegex(ValueError, "Apply failed"):
            backend.activate(self.display, self.db, {"name": "after"}, require_confirmation=False)
        self.assertEqual(self.display.current, {"name": "before"})
        self.assertFalse(backend.pending_path().exists())

    def test_ambiguous_ddc_target_never_receives_write(self):
        preset = {"claim_inputs": True,
                  "inputs": [{"connector": "HDMI-1", "edid": "duplicate", "code": 17}]}
        with patch.object(backend, "drm_displays", return_value=[{"edid": "duplicate", "bus": 9},
                                                                {"edid": "duplicate", "bus": 10}]), \
                patch.object(backend.subprocess, "run") as run:
            self.assertEqual(len(backend.claim_inputs(preset)), 1)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

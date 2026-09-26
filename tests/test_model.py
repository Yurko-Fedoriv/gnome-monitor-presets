import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extension"))
from model import snapshot, resolve, signature


def state():
    a = ["DP-1", "ABC", "Panel", "123"]
    b = ["HDMI-1", "XYZ", "Other", "456"]
    mode = ["mode-id", 3840, 2160, 143.851348, 1.5, [1.0, 1.5],
            {"is-current": True, "refresh-rate-mode": "variable"}]
    return [42, [[a, [mode], {"color-mode": 1, "supported-color-modes": [0, 1],
                             "rgb-range": 2, "is-underscanning": False}],
                  [b, [["other", 1920, 1080, 60, 1, [1], {}]], {}]],
            [[0, 0, 1.5, 1, True, [a], {}]],
            {"layout-mode": 1, "supports-changing-layout-mode": True}]


class ModelTests(unittest.TestCase):
    def test_capture_full_precision_and_disabled_display(self):
        saved = snapshot(state())
        self.assertEqual(len(saved["connected"]), 2)
        self.assertEqual(len(saved["logical"]), 1)
        group = saved["logical"][0]
        self.assertEqual((group["scale"], group["transform"], group["primary"]), (1.5, 1, True))
        self.assertEqual(group["monitors"][0]["refresh"], 143.851348)
        self.assertEqual(group["monitors"][0]["options"],
                         {"color-mode": 1, "rgb-range": 2, "underscanning": False})

    def test_connector_and_mode_ids_can_change_without_losing_identity(self):
        live = state()
        saved = snapshot(live)
        live[1][0][0][0] = "DP-4"
        live[1][0][1][0][0] = "new-id"
        result = resolve(saved, live)
        self.assertEqual(result["logical"][0]["monitors"][0]["spec"][0], "DP-4")
        self.assertEqual(result["logical"][0]["monitors"][0]["mode"], "new-id")
        self.assertEqual(signature(saved), signature(result))

    def test_missing_active_display_rejected(self):
        live = state()
        saved = snapshot(live)
        live[1].pop(0)
        with self.assertRaisesRegex(ValueError, "missing"):
            resolve(saved, live)

    def test_missing_disabled_display_allowed(self):
        live = state()
        saved = snapshot(live)
        live[1].pop(1)
        resolve(saved, live)

    def test_refresh_and_variable_rate_must_match(self):
        for change in (lambda mode: mode.__setitem__(3, 144.0),
                       lambda mode: mode[6].__setitem__("refresh-rate-mode", "fixed")):
            live = state()
            saved = snapshot(live)
            change(live[1][0][1][0])
            with self.assertRaisesRegex(ValueError, "Exact saved mode"):
                resolve(saved, live)

    def test_unsupported_scale_or_hdr_rejected(self):
        live = state()
        saved = snapshot(live)
        live[1][0][1][0][5] = [1]
        with self.assertRaisesRegex(ValueError, "scale"):
            resolve(saved, live)
        live = state()
        live[1][0][2]["supported-color-modes"] = [0]
        with self.assertRaisesRegex(ValueError, "color"):
            resolve(saved, live)

    def test_ambiguous_monitor_rejected(self):
        live = state()
        saved = snapshot(live)
        live[1][0][0][0] = "DP-2"
        duplicate = copy.deepcopy(live[1][0])
        duplicate[0][0] = "DP-3"
        live[1].append(duplicate)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            resolve(saved, live)

    def test_mirror_group_preserved(self):
        live = state()
        live[1][1][1][0][6]["is-current"] = True
        live[2][0][5].append(live[1][1][0])
        saved = snapshot(live)
        self.assertEqual(len(saved["logical"]), 1)
        self.assertEqual(len(saved["logical"][0]["monitors"]), 2)

    def test_order_does_not_change_active_signature(self):
        a = snapshot(state())
        b = copy.deepcopy(a)
        b["connected"].reverse()
        self.assertEqual(signature(a), signature(b))


if __name__ == "__main__":
    unittest.main()

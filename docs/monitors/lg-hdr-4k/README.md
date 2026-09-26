# LG HDR 4K: 27UK650-W and 27UK850-W

Implementation: [lg_hdr.py](../../../extension/monitor_drivers/lg_hdr.py).
Matches the existing EDID manufacturer/product pair `GSM` / `LG HDR 4K`.
That pair is shared by multiple models; it is not proof every matching monitor
supports this workaround. Physical testing covers the two models above.

## Why this driver exists

Standard VCP 60 input writes caused Out of Range messages, incorrect OSD input
state and loss of control on the tested monitors. Repeating writes or falling
back to the standard command is not a recovery strategy. Soft power cycling or
selecting an empty input and switching back restored control during testing.

The tested alternative uses vendor feature **F4**, source address **0x50**, MCCS
2.2, no verification and one write attempt. It is a write-only request: success
means the command was sent, not that the picture was independently verified.

| Saved input code | UI label | F4 value |
| --- | --- | --- |
| 15 | DisplayPort | D0 |
| 16 | USB-C, only with override | D1 |
| 17 | HDMI 1 | 90 |
| 18 | HDMI 2 | 91 |

The saved code is a stable extension identifier. In particular, 16 is not a
claim that standard MCCS DP2 and USB-C are interchangeable.

## Discovery and manual setting

Both tested LGs advertise the same input list, including a phantom DP2. The
27UK850-W has USB-C video and the 27UK650-W does not. **Has Type-C** is a manual
boolean stored under the existing `usb_c` cache key, indexed by monitor identity.
It saves immediately, survives refresh and connector changes, and exposes input
16 only when enabled. USB-C switching was physically confirmed on 27UK850-W.
Do not infer the physical USB-C port from this shared EDID model name.

## Reachability and evidence

Active HDMI -> DP worked using F4, with the OSD agreeing. Inactive HDMI while
another computer used DP/USB-C often returned ENXIO even with EDID still visible.
Standard input readback on these LGs is unreliable, so the driver does not use
it for current-input detection or a preliminary reachability query.

Earlier tests with AMD integrated graphics found valid brightness replies over
dock DP but no visible effect from F4 writes; direct USB-C also failed. Direct
HDMI input switching worked. These observations do not identify whether the
remaining limitation is in the GPU path, driver, or monitor firmware, and do not
establish a universal DP workaround. No CEC or sleeping-input solution was
confirmed. Software cannot promise to reclaim these displays from every input.

The extension skips disabled layout targets and sends independent monitor buses
concurrently, so an unreachable LG does not block sending the MSI command.
It still waits for command results before completing the action.

Prerequisites are the same as [generic DDC](../generic-ddc/README.md).
Protocol reference: [ddcutil LG input notes](https://github.com/rockowitz/ddcutil/wiki/Switching-input-source-on-LG-monitors).
Never broaden this profile or add new vendor values without evidence and an
explicitly authorized physical test.

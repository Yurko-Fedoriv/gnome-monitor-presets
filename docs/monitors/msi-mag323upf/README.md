# MSI MAG323UPF USB control

Implementation: [msi_mag.py](../../../extension/monitor_drivers/msi_mag.py), with
the USB exchange/button reader in [msi.py](../../../extension/msi.py).
Matches the existing model string `MSI MAG323UPF`; it does not automatically
apply to other MSI models. USB controller VID:PID is `1462:3fa4`.

## Setup

Run `./hardware/enable-msi-access.sh` from the repository once. It installs a
udev rule granting the active local desktop user access only to this MSI HID
controller type; the script requests sudo for installing that rule. Ordinary
operation needs neither root nor MSI Gaming Intelligence. Reconnect the USB
controller if your session has not acquired access yet.

The current implementation requires exactly one matching controller. It does
not yet associate multiple MSI controllers with multiple display EDIDs. Do not
pick the first device or silently broaden support to other vendor products.

## Inputs and button

The input list is a known model profile validated during explicit refresh by a
USB current-input query. It is not a query enumerating physical sockets.

| Saved input code | Label | USB value |
| --- | --- | --- |
| 15 | DisplayPort | 002 |
| 16 | USB-C | 003 |
| 17 | HDMI 1 | 000 |
| 18 | HDMI 2 | 001 |

Report ID 1, ASCII commands ending in CR, 64-byte padded reports on Linux:
query `58` + setting, response `01` + ASCII `5b` + setting + decimal value.
Setting `00500` reads the current input, `00110` reads the Macro Key, and `008>0`
reads KVM mode. Input writes are `5b00500` + three-digit decimal value.
The expected write acknowledgement begins with `01` + ASCII `5600+`.

The helper reads the current input before switching and avoids redundant writes.
Switching to USB-C may move USB to the other computer before the acknowledgement
arrives. If the controller disappears, no second input write is attempted.
The Macro Key is polled at 250 ms only while a trigger is configured. Each
reconnection establishes a baseline; only a subsequent rising edge activates
an action. Queries and writes use one shared lock. Competing external readers
may consume the same button state.

## Reachability and tested behavior

USB ownership is separate from video input. On the tested Auto-KVM setup,
USB-C selected the other computer, while DP and HDMI kept USB with Ubuntu.
From HDMI 2 showing a TV streamer, the Ubuntu USB helper successfully selected
DP; readback and the user's picture observation agreed. DP -> USB-C, Macro Key
activation, and the action-induced KVM suppression were also physically tested.

This does **not** mean the controller is reachable from both computers at once.
If USB has moved away, the helper must wait for it to return. USB presence alone
also does not guarantee permissions or a successful response.

To preserve existing action behavior, the shared EDID/connected-bus checks and
enabled-layout requirement still apply even for this USB driver. Relaxing these
requirements for USB-only recovery would be a separate functional change.
GNOME lock-screen trigger support is tested in isolated sessions; the physical
locked HDMI-to-DP scenario has not yet been explicitly confirmed.

MSI DDC current-input reads worked during investigation, but capability queries
were unreliable. This driver uses USB; it never falls back to DDC on failure.
Protocol reference: [couriersud/msigd](https://github.com/couriersud/msigd).

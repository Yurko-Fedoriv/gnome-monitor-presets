# Generic DDC/CI

Implementation: [generic_ddc.py](../../../extension/monitor_drivers/generic_ddc.py).
This is the fallback for monitors without a specific driver. Compatibility with
arbitrary monitors is unverified; support for DDC/CI does not guarantee support
for changing inputs from an inactive video connection.

Install `ddcutil` and use your distribution's I2C permission setup. The extension
runs as your user and never elevates monitor commands. Display layout management
does not need DDC. Discovery reads advertised VCP 60 values with the capability
cache disabled, only when requested. Failed refreshes preserve previous results.
Before any discovery, choices retain the existing default DP1/DP2/HDMI1/HDMI2
list; these defaults are not proof those sockets exist. Unusual advertised codes
are retained with a hexadecimal fallback label.

Switching reads VCP 60, skips an already-selected input, writes the requested
value with `--noverify`, then tries a readback. Unsupported reads do not prevent
a write; an interrupted post-write read does not cause another write. A mismatched
readback is recorded as failure. Calls retain the existing 8-second timeout and
ddcutil retry defaults; capability discovery uses a 20-second timeout.

Actions first require the saved EDID to match the connected display and the
monitor to be enabled in the current GNOME layout. EDID presence and an enabled
layout are only eligibility checks: neither establishes that DDC is listening.
No additional preflight probe is performed. Unknown monitors are not scanned for
vendor commands or granted a vendor-specific fallback.

References: [setvcp](https://www.ddcutil.com/command_setvcp/),
[capabilities](https://www.ddcutil.com/command_capabilities/),
[troubleshooting](https://www.ddcutil.com/faq/).

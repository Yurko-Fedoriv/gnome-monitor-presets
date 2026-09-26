# Adding a monitor driver

Monitor Presets separates layout/action orchestration from input control. Driver
code lives in `extension/monitor_drivers/`; the explicit registry in `__init__.py`
selects specific implementations before the generic DDC fallback. This is a
small built-in plugin interface, not an installer or loader for arbitrary code
from configuration directories. Adding a driver requires a source update.

## Boundaries

| Layer | Owns |
| --- | --- |
| `model.py`, `native.py`, backend transactions | GNOME layout, recovery, login defaults |
| `input_actions.py` | Saved action identity, eligible targets, assembling requests |
| `inputs.py` | Identity-keyed discovery cache, retaining old values on failures |
| `monitor_drivers` | Input choices, discovery, optional settings, eligibility policy, transport execution |
| backend input dispatcher | Current EDID/bus checks, per-bus concurrency, combined diagnostics |
| `msi.py` | MSI HID exchanges, shared USB lock, Macro Key reader |
| `inputPrefs.js` | Rendering declared boolean options without model-specific branches |

No hardware access occurs on import. Actual refresh and switching are explicit
operations. Changing presets or restoring login layouts does not send monitor
input commands. Macro Key triggers remain an MSI-specific trigger integration;
the input-driver abstraction does not pretend all monitors have hardware buttons.

## Driver contract

Use `GenericDDC` as the implementation reference and override only what differs:

- `id`, `transport`: stable implementation and legacy transport identifiers.
- `channel`, `readback`, `setup`: describe the control path, readback reliability,
  and any separate permission/dependency setup. These describe capability, not
  a claim of live connectivity.
- `matches(spec)`: narrow match using `[connector, vendor, product, serial]`.
  Never match a personal connector or serial as a general compatibility rule.
  Overlapping specific matches are rejected instead of guessed.
- `choices(entry)`: list of `{code, label}` from cached data/manual options;
  no I/O. Treat saved numeric codes as an API: do not reinterpret existing ones.
- `discover(target, displays)`: read-only explicit refresh; returns a cache
  fragment such as `codes`, `raw`, `source`. Core retains options, adds timestamp
  and EDID, and leaves the previous entry intact if discovery fails.
- `manual_options`: boolean descriptors with `key`, `type`, `label`, `tooltip`,
  `default`. Core adds `value` for the UI and validates updates. Extend the
  descriptor validator/UI deliberately if another data type becomes necessary.
- `check_target(target, current)`: cheap eligibility checks before creating a
  request. Current drivers preserve the enabled-layout requirement. No expensive
  liveness probe, and no treating EDID visibility as DDC acknowledgement.
- `profile(code)`: optional transport settings for a request. MSI resolves a
  unique available controller here; LG returns an explicitly supported F4 value.
- `default_transport` and `allows_transport(name)`: legacy dispatch safeguards.
  LG defaults to blocked unless an explicit profile exists; standard VCP 60
  remains forbidden even if an old configuration requests it.
- `switch(code, bus, profile, report, read)`: execute one request, updating its
  report; `read` is the generic VCP60 query callback. Return normally on success
  or raise a descriptive `OSError`/`ValueError`/timeout. Do not retry another
  transport after a vendor protocol failure. No cache/settings/file writes here.

Register the instance in `DRIVERS`; `TRANSPORTS` indexes those instances and the
fallback. The registered driver implementation is trusted project code.
A runtime profile is data, never a Python import path or executable command.

Examples: [generic DDC](monitors/generic-ddc/README.md),
[LG F4 and a manual option](monitors/lg-hdr-4k/README.md),
[MSI USB](monitors/msi-mag323upf/README.md).

## Identity and reachability

Four different states matter: present in saved presets, EDID currently visible,
enabled in GNOME, and controllable through the chosen transport. None should be
silently substituted for another. USB ownership may remain here while the video
shows a different input; DDC may disappear while EDID remains visible.

The refactor intentionally preserves existing eligibility rules: actions match
vendor/product/serial, confirm EDID, reject disabled layout targets, then resolve
the driver. At dispatch all requests still need one matching EDID and a DDC bus,
even MSI USB requests. This conservative shared check is a known limitation, not
a requirement of USB HID. Do not remove it as a refactoring side effect.

Independent buses run concurrently; commands on the same bus stay sequential.
The action waits for all input results before its optional preset and before
finishing one-shot KVM suppression. Driver switches must not call GNOME layout
APIs, touch the KVM guard, or spawn detached input writes. If a new transport is
not represented by a DDC bus, design a transport-specific scheduling key and
eligibility change separately, with regression coverage and hardware evidence.

## Compatibility and contribution evidence

Document exact model/connection/OS tested, matching scope, input values, current
input reliability, inactive-input behavior, same-input behavior, permission needs,
and recovery. Distinguish command acceptance from physical confirmation. Use
synthetic serials, EDIDs and USB paths in fixtures; do not commit raw user logs.
Keep protocol citations and any upstream copyright/license notices.

Run `/usr/bin/python3 -m unittest discover -s tests -v` and the isolated GNOME
smoke test, then inspect the distributable zip for the new module. Tests should
cover dispatch, cache compatibility, unsafe fallback rejection and failure
handling. A UI descriptor change also needs preferences testing. Hardware tests
are separate and require the user to be ready for the specific transition.

Install with `/usr/bin/python3 install.py` only. It replaces schemas atomically;
never compile/copy over a live installed `gschemas.compiled`.
For agent-assisted work, see [the add-monitor-driver skill](../skills/add-monitor-driver/SKILL.md).

## Brightness and onboard audio

`controls.py` handles standard VCP 10 (brightness), 62 (speaker volume), and 8D
(audio mute) independently of input switching. It never sends VCP 60 or vendor
input commands. See [ddcutil feature definitions](https://www.ddcutil.com/vcpinfo_output/)
and [brief response formats](https://www.ddcutil.com/command_getvcp/).

Read-only queries on the current LG 27UK650/27UK850 and MSI MAG323UPF returned
continuous brightness/volume ranges of 0–100 and simple mute values 1/2. This
establishes readable controls, not physical verification of writes. Unsupported,
complex mute responses, invalid ranges and unreachable devices are omitted.
Every write revalidates active monitor identity, EDID, bus and current feature
range; mute writes use only audio values 1/2, never screen-blank bits. Hardware
writes still need a user-ready physical test. Automated tests mock DDC writes.

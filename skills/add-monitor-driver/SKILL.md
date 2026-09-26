---
name: add-monitor-driver
description: Add or refine a Monitor Presets GNOME extension driver for monitor input discovery, switching, transport quirks, and manual capability settings. Use when adding hardware support to this repository; not for Windows utilities or GNOME layout-only changes.
---

Read `../../docs/monitor-drivers.md` relative to this file, then the closest
existing driver and its model README. Keep layout transactions, KVM suppression
and trigger orchestration outside the driver. Register narrowly matched built-in
implementations; do not load executable plugins from user configuration.

Separate evidence from assumptions: monitor/firmware identity, control transport,
input codes, report framing, readback reliability and ability to respond while
showing another input. Discoverability, enabled layout and control reachability
are separate facts. Start with local read-only evidence and primary protocol
sources. Do not guess USB-C codes from connector labels or generalize a vendor's
protocol to every model. A device's success return is not visible confirmation.

Preserve numeric action codes and cache keys. Prefer a declared boolean option
for a known ambiguous capability (LG's `usb_c` is the example); don't add model
branches to preferences. Report unsupported combinations and retain cached
results on discovery failure. Never fall back from the LG F4 transport to VCP60,
or repeat speculative writes after a timeout/disconnection.

Use mocked transport tests for commands, skipped targets, unavailable devices,
cache preservation and same-input no-op. Run the Python suite and isolated GNOME
smoke test when changing runtime code. Ensure packaging includes the module and
licenses but no caches or personal data. Use synthetic identifiers in fixtures.

For actual input writes, first establish that the user is ready for that exact
transition (including losing keyboard/mouse through KVM). Existing explicit
readiness is sufficient; don't repeatedly ask for permission. If no readiness is
available, finish code, documentation and simulated tests without switching live
hardware. Never turn a test into repeated random vendor commands. State what is
physically confirmed and what remains untested.

Document the model-specific behavior next to the existing monitor READMEs, with
source attribution. Use the atomic installer from AGENTS.md for authorized
updates. Do not copy over an installed compiled schema. Keep unrelated artifacts
and raw reports out of version control.

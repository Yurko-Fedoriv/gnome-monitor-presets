# License and references

Monitor Presets is free software: you may redistribute it and/or modify it under
the GNU General Public License as published by the Free Software Foundation,
either version 2 of the License, or (at your option) any later version.
SPDX identifier: **GPL-2.0-or-later**. Copyright 2026 Monitor Presets contributors.
See [LICENSE](LICENSE) for the terms, including the warranty disclaimer.

This choice fits GNOME Shell's GPL-2.0-or-later code and the GPLv2 protocol
reference used during development. MIT/BSD would be reasonable for an entirely
independent permissive library, but this extension is integrated with GNOME
Shell and was developed with GPL implementations as references. A permissive
project label would not remove obligations for any upstream-derived material.

References used during development:

- GNOME Shell and Mutter: session modes, popup/switcher APIs, display D-Bus
  interface and native monitor configuration format. Their implementations and
  authors retain their upstream copyrights. GNOME's libraries and resources are
  provided by the operating system, not bundled here.
- [couriersud/msigd](https://github.com/couriersud/msigd): MSI HID protocol
  reference, GPLv2. This repository's Python implementation uses the documented
  command identifiers; it does not bundle the msigd executable or C++ sources.
- [ddcutil](https://www.ddcutil.com/) and its
  [LG input notes](https://github.com/rockowitz/ddcutil/wiki/Switching-input-source-on-LG-monitors):
  command-line interface and alternate LG protocol reference. ddcutil is an
  optional separately installed program, not bundled here.

Monitor and company names identify compatibility; they imply no endorsement.
New contributions must identify any copied/adapted upstream code and preserve
its notices. Protocol facts and compatibility observations are not a substitute
for checking the license of an implementation before copying it.

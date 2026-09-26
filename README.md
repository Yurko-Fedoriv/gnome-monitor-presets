# Monitor Presets

An experimental GNOME Shell 50 extension for saving exact display layouts,
choosing them with Super+P, and running monitor/KVM actions from shortcuts.
The panel indicator shows the number of enabled displays and a layout preview.

Developed and tested on Ubuntu with GNOME 50 and a small set of monitors. Other
GNOME versions are not supported yet. This project is distributed from source;
it has not been submitted to extensions.gnome.org.

## Install

Requires GNOME Shell 50, Python 3 with PyGObject (`python3-gi`), and GLib's schema
compiler. Input switching optionally needs `ddcutil` or the supported monitor's
USB access setup; saving and applying layouts does not.

```sh
/usr/bin/python3 install.py
```

Log out and back in for GNOME to discover the extension, then enable it:

```sh
gnome-extensions enable monitor-presets@local
```

Open preferences from the indicator. Arrange displays in GNOME Settings, then
save a named layout in preferences or with **Save current layout…** in the menu.
For example, save a single-display layout and a full-desk layout. There is no
requirement to have three monitors or a KVM.

To build a distributable zip, run `sh package.sh`. The artifact is
`dist/monitor-presets@local.shell-extension.zip`. Build and installation stage
files before publishing them. **Never overwrite an installed `gschemas.compiled`
in place or compile schemas inside the live extension directory:** GNOME may
have it memory-mapped. The installer replaces files atomically to avoid this.

After updates, log out/in for changed Shell code or schemas; preferences-only
changes need reopening preferences. Saved layouts and actions survive updates.

## Presets

Hold Super and press P to browse previews; release Super to apply. Left/right
select and Escape cancels. The display hardware key uses the same chooser.
Unavailable presets are omitted from the chooser and disabled in the panel menu,
with the reason shown in preferences. Presets can be renamed, replaced, reordered
and deleted.

Preserved settings include:

- Enabled/disabled displays, mirror groups, position, rotation/reflection, scale
  and primary display.
- Resolution, full-precision refresh rate, fixed/variable refresh mode and
  interlacing.
- HDR/color mode, RGB range and underscanning where exposed by Mutter.
- Mutter output luminance, GNOME Night Light, privacy-screen preference and
  compositor-exposed backlight values where supported.

Displays are matched by vendor/product/serial, with the connector disambiguating
otherwise identical displays. Mode IDs are refreshed against current capabilities;
missing saved modes, scales or enabled displays are reported rather than silently
approximated. Missing displays that were disabled in the preset do not block it.
Global experimental GNOME flags, window positions, unknown future settings and
monitor OSD settings beyond explicitly configured input switching are not saved.

Presets apply immediately by default. **Confirm display layout changes** adds a
30-second Keep/Revert dialog. An independent helper protects the apply step in
both modes; a failed apply attempts restoration. Without confirmation, a
successful but unwanted layout has no timeout rollback. **Restore previous
layout** retains an undo snapshot across sessions. Undo restores GNOME settings,
not monitor inputs or application window positions.

## Login defaults

Choose **Last activated preset** or **Always use a fixed preset**. The selected
default is synchronized into `~/.config/monitors.xml`, so Mutter can restore it
before the extension starts. Unrelated native configurations/policies are kept;
invalid or unfamiliar XML is left untouched and reported. Backups live in
`~/.config/monitor-presets/native-backups/` and identical backups are reused.

Login fallback compares the current layout before applying. A matching layout
is left alone; preference-only differences avoid a display modeset. The login
guard distinguishes new compositor sessions from extension re-enabling, even
when the user bus survives logout. Disabling restoration stops synchronization;
it does not erase the native layout already written. GDM's separate pre-login
configuration is not modified.

## Actions and KVM

A named **Action** can have multiple keyboard shortcuts, a KVM-disconnect trigger
and/or the supported MSI Macro Key. Each shortcut and each hardware trigger can
belong to only one action. Conflicting keyboard shortcuts are reported rather
than replacing another application's binding.

Actions optionally apply a preset and independently redirect selected monitors
to other inputs. **Keep current** leaves the GNOME layout alone. Enabling a
monitor in the chosen preset while redirecting it is allowed, with a soft warning.
Input requests run before the preset, while outgoing monitors still have a signal.
Action presets apply immediately through the rollback watchdog and normal login
policy. Input-only actions do not change the layout or native login default.

Actions with input redirects also appear below presets in the menu. Preset-only
actions remain available through their triggers. Changes save immediately.

**KVM Disconnect** watches a selected USB device, not a particular monitor model.
A 40-second autodetection flow helps identify devices that disappear when the KVM
moves to another computer. Detected devices stay at the top of the chooser.
Compatibility depends on the KVM actually disconnecting the watched device;
a KVM that emulates a permanently connected keyboard may need another device
or a different trigger. Startup/suspend establish a baseline; reconnect does not
run an action.

An action-induced KVM disconnect is suppressed once. The next physical disconnect
can run normally; the guard expires if no disconnect occurs. Overlapping action
requests are discarded rather than queued. Missing, disabled or unreachable
targets are skipped quietly and recorded in diagnostics. Independent monitor
buses progress concurrently, with commands sharing one bus kept sequential.

Configured action hotkeys, KVM detection and MSI Macro Key handling continue
while the logged-in session is locked. The menu and Super+P chooser remain
unavailable while locked; actions do not unlock the session. This does not add
support for the login screen before signing in.

## Monitor input support

Connect and activate the monitors here, then press **Refresh display inputs** in
preferences. Discovery is cached by monitor identity and never runs automatically
at login. Failed refreshes retain previous results. Input choices and manual
capability settings come from the selected monitor driver.

| Driver | Control path | Evidence / limitations |
| --- | --- | --- |
| [Generic DDC](docs/monitors/generic-ddc/README.md) | Standard VCP 60 | Fallback for other monitors; model compatibility unverified |
| [LG HDR 4K](docs/monitors/lg-hdr-4k/README.md) | Alternate F4 DDC command | Tested 27UK650-W / 27UK850-W; inactive-input control is limited; standard writes blocked |
| [MSI MAG323UPF](docs/monitors/msi-mag323upf/README.md) | Dedicated USB HID | Tested input switching and Macro Key; requires USB ownership and user access |

Connected, enabled and controllable are different states. A monitor may advertise
EDID while showing another computer and ignore control commands. A USB controller
may remain reachable even while the monitor shows another video input. See each
driver's README for the tested behavior and setup. Input switching is optional;
these hardware limitations do not prevent using GNOME presets.

Saved destinations follow vendor/product/serial across connector moves. Writes
still validate EDID. If an adapter changes EDID, refresh and reselect the
destination; saved layouts may also need updating. The current MSI path requires
one matching controller and preserves the shared enabled-layout/EDID/bus checks.

## Diagnostics, recovery and removal

User data is in `~/.config/monitor-presets/`; settings/actions are also in the
`org.gnome.shell.extensions.monitor-presets` GSettings schema. Back up both when
moving machines. `presets.json` holds layouts; `pending.json` holds an outstanding
recovery transaction.

`diagnostics.log` rotates at 256 KiB with one backup. `last-input-check.json`
contains per-monitor input results and errors. These can contain device names,
serials and EDID fingerprints: redact them before attaching to a public issue.

For manual diagnosis after installation:

```sh
/usr/bin/python3 "$HOME/.local/share/gnome-shell/extensions/monitor-presets@local/backend.py" status
# Use the token from pending.json only if a transaction is pending:
/usr/bin/python3 "$HOME/.local/share/gnome-shell/extensions/monitor-presets@local/backend.py" revert TOKEN
```

Disable with `gnome-extensions disable monitor-presets@local`. This restores the
stock switch-monitor handler; an outstanding watchdog still recovers an
unconfirmed layout. To uninstall, disable first and run
`gnome-extensions uninstall monitor-presets@local`. User settings/layouts remain.
If you installed the optional MSI udev rule, its removal is documented by the
setup script's installed path; uninstalling the extension does not remove it.

## Development

```sh
/usr/bin/python3 -m unittest discover -s tests -v
bash tests/smoke-shell.sh
```

The smoke test uses separate headless GNOME sessions and virtual monitors. It
covers actual layout transitions/restoration, rollback, login/native restoration,
menu/switcher/dialogs, preferences, action dispatch and lock/unlock mode handling.
It does not switch the live desktop. Missing login-session/portal warnings in
these artificial sessions are expected. Test logs include their temporary path.
Physical hardware coverage is documented separately in each driver README.

[Driver development](docs/monitor-drivers.md) explains the interface and stable
configuration contracts. The repository includes an
[add-monitor-driver skill](skills/add-monitor-driver/SKILL.md) for agent-assisted
contributions. Read [AGENTS.md](AGENTS.md) for safe local development.

## License and references

GPL-2.0-or-later; see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

- [Mutter display configuration interface](https://github.com/GNOME/mutter/blob/50.1/data/dbus-interfaces/org.gnome.Mutter.DisplayConfig.xml)
- [Mutter native configuration parser](https://github.com/GNOME/mutter/blob/50.1/src/backends/meta-monitor-config-store.c)
- [GNOME session modes](https://gjs.guide/extensions/topics/session-modes.html)
- Hardware protocol references are linked from the individual driver READMEs.

### Monitor brightness and sound

Expand a monitor's statistics row in the panel menu to read its hardware controls.
Brightness and volume sliders use the monitor's own DDC settings; the mute button
also controls the monitor itself. Unsupported controls are omitted. Values are
read again on opening and after changes, so the monitor's OSD remains authoritative.
These controls require `ddcutil` and access to the monitor's I2C bus.

**Output here** selects the computer's audio destination using GNOME's output
routing and shows a checkmark while selected. Use the adjacent arrow to associate
an HDMI/DisplayPort audio output with that monitor first. Associations are saved;
automatic matching is used only when the monitor name and output are unambiguous.
Two identically named LGs therefore require an explicit choice. Routing does not
change software volume or software mute, and an advertised audio output does not
necessarily mean the monitor contains speakers (it may have a headphone socket).

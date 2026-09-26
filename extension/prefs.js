import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import GLib from 'gi://GLib';
import {fullValueCombo} from './preferencesWidgets.js';
import {usbDevices, usbKey} from './kvm.js';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import {run, summary} from './client.js';
import {inputPreferences} from './inputPrefs.js';

export default class Preferences extends ExtensionPreferences {
    async fillPreferencesWindow(window) {
        window.set_default_size(760, 740);
        this._settings = this.getSettings();
        this._window = window;
        this._page = new Adw.PreferencesPage({title: 'Monitor Presets', icon_name: 'video-display-symbolic'});
        window.add(this._page);
        const shortcuts = new Adw.PreferencesGroup({title: 'Preset switching',
            description: 'Super+P selects a saved layout; releasing Super applies it.'});
        this._page.add(shortcuts);
        const confirm = new Adw.SwitchRow({title: 'Confirm display layout changes',
            subtitle: 'Ask to keep each change; revert automatically after 30 seconds. Off applies presets immediately.'});
        this._settings.bind('confirm-layout-changes', confirm, 'active', Gio.SettingsBindFlags.DEFAULT);
        shortcuts.add(confirm);
        const startup = new Adw.PreferencesGroup({title: 'After login',
            description: 'Saves the selected default in GNOME’s native display configuration so the desktop starts with it. The login screen is managed separately.'});
        this._page.add(startup);
        const syncSignals = ['restore-at-login', 'startup-policy', 'fixed-preset'].map(key =>
            this._settings.connect(`changed::${key}`, () => {
                Gio.Settings.sync();
                this._run('sync-native');
            }));
        window.connect('close-request', () => {
            this._closed = true;
            this._clearCapabilityAudio?.();
            this._clearDeviceRow();
            this._stopDetection();
            for (const signal of syncSignals)
                this._settings.disconnect(signal);
            return false;
        });
        const restore = new Adw.SwitchRow({title: 'Restore a preset after login'});
        this._settings.bind('restore-at-login', restore, 'active', Gio.SettingsBindFlags.DEFAULT);
        startup.add(restore);
        const policy = fullValueCombo({title: 'Default layout',
            model: Gtk.StringList.new(['Last activated preset', 'Always use a fixed preset']),
            selected: this._settings.get_string('startup-policy') === 'fixed' ? 1 : 0});
        policy.connect('notify::selected', () => {
            this._fixed.visible = policy.selected === 1;
            this._settings.set_string('startup-policy', policy.selected === 1 ? 'fixed' : 'last');
        });
        startup.add(policy);
        this._fixed = fullValueCombo({title: 'Fixed preset', visible: policy.selected === 1});
        startup.add(this._fixed);
        this._fixed.connect('notify::selected', () => {
            if (!this._loading && this._presets?.[this._fixed.selected])
                this._settings.set_string('fixed-preset', this._presets[this._fixed.selected].id);
        });
        const actions = new Adw.PreferencesGroup({title: 'Save a layout',
            description: 'Arrange displays in GNOME Settings, then save them here or from the panel indicator.'});
        this._page.add(actions);
        const name = new Adw.EntryRow({title: 'New preset name'});
        const save = new Gtk.Button({label: 'Save', valign: Gtk.Align.CENTER, sensitive: false});
        let saving = false;
        const updateSave = () => { save.sensitive = !saving && Boolean(name.text.trim()); };
        const saveLayout = async () => {
            const title = name.text.trim();
            if (saving || !title) return;
            saving = true;
            updateSave();
            try {
                if (await this._run('save', title)) {
                    name.text = '';
                    await this._reload();
                }
            } finally {
                saving = false;
                updateSave();
            }
        };
        name.connect('notify::text', updateSave);
        name.connect('entry-activated', saveLayout);
        save.connect('clicked', saveLayout);
        name.add_suffix(save);
        actions.add(name);
        await this._reload();
    }

    _stopDetection() {
        if (this._detectTimer)
            GLib.source_remove(this._detectTimer);
        this._detectTimer = 0;
        if (this._settings)
            this._settings.set_double('kvm-detect-until', 0);
    }

    _clearDeviceRow() {
        if (!this._deviceRow) return;
        this._deviceRow.factory = null;
        this._deviceRow.list_factory = null;
        this._deviceRow.model = null;
        this._deviceRow = null;
    }

    async _reloadKvm() {
        this._stopDetection();
        const previousGroup = this._kvmGroup;
        this._kvmGroup = null;
        this._clearDeviceRow();
        if (previousGroup) this._page.remove(previousGroup);
        const group = new Adw.PreferencesGroup({title: 'KVM Disconnect', description:
            'Choose the USB device to watch. Assign the KVM disconnect trigger to an action below. Reconnecting does nothing.'});
        this._kvmGroup = group;
        this._page.add(group);
        let config;
        try { config = JSON.parse(this._settings.get_string('kvm-config')); } catch (_) { config = {}; }
        const persist = () => this._settings.set_string('kvm-config', JSON.stringify(config));
        const enabled = new Adw.SwitchRow({title: 'Enable KVM disconnect handling'});
        this._settings.bind('kvm-disconnect-enabled', enabled, 'active', Gio.SettingsBindFlags.DEFAULT);
        group.add(enabled);
        const detectedKeys = new Set((config.detected || []).map(usbKey));
        const availableDevices = () => {
            const current = usbDevices();
            for (const saved of [...(config.detected || []), ...(config.usb ? [config.usb] : [])]) {
                if (!current.some(d => usbKey(d) === usbKey(saved)))
                    current.push({...saved, name: `${saved.name || 'Saved USB device'} · disconnected`});
            }
            current.sort((a, b) => Number(detectedKeys.has(usbKey(b))) - Number(detectedKeys.has(usbKey(a))) ||
                Number(b.hub) - Number(a.hub));
            return current;
        };
        let devices = availableDevices();
        let updatingDevices = false;
        let deviceRow;
        const deviceNames = () => devices.map(d => `${detectedKeys.has(usbKey(d)) ? 'Detected · ' : ''}${d.name}`);
        deviceRow = fullValueCombo({name: 'usb-device-to-watch',
            model: Gtk.StringList.new(deviceNames()),
            selected: config.usb ? devices.findIndex(d => usbKey(d) === usbKey(config.usb)) : Gtk.INVALID_LIST_POSITION});
        this._deviceRow = deviceRow;
        deviceRow.update_property([Gtk.AccessibleProperty.LABEL], ['USB device to watch']);
        const deviceTitle = new Gtk.Box({spacing: 6, valign: Gtk.Align.CENTER});
        deviceTitle.append(new Gtk.Label({label: 'USB device to watch'}));
        deviceTitle.append(new Gtk.Image({icon_name: 'dialog-information-symbolic', pixel_size: 16,
            tooltip_text: 'Previously detected devices stay at the top, followed by hubs. Devices without serial numbers are tied to their USB port.'}));
        deviceRow.add_prefix(deviceTitle);
        group.add(deviceRow);
        const detect = new Gtk.Button({label: 'Autodetect…', valign: Gtk.Align.CENTER});
        const detectRow = new Adw.ActionRow({title: 'Identify the KVM USB device',
            subtitle: 'Watches which devices disappear and return. KVM actions are paused during detection.'});
        detectRow.add_suffix(detect);
        group.add(detectRow);
        detect.connect('clicked', () => {
            const dialog = new Adw.AlertDialog({heading: 'Detect KVM device', body:
                'After pressing Start, switch the KVM to the other computer, wait at least 5 seconds, then switch back. Detection lasts 40 seconds. Any matching devices will appear at the top of the dropdown.'});
            dialog.add_response('cancel', 'Cancel');
            dialog.add_response('start', 'Start');
            dialog.connect('response', (_d, response) => {
                if (response !== 'start' || this._closed)
                    return;
                const baseline = usbDevices();
                const missing = new Map();
                const matches = new Set();
                const deadline = Date.now() / 1000 + 40;
                this._settings.set_double('kvm-detect-until', deadline + 2);
                detect.sensitive = false;
                this._detectTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
                    const now = Date.now() / 1000;
                    const present = new Set(usbDevices().map(usbKey));
                    for (const d of baseline) {
                        const key = usbKey(d);
                        if (!present.has(key)) {
                            if (!missing.has(key)) missing.set(key, now);
                        } else if (missing.has(key)) {
                            if (now - missing.get(key) >= 3) matches.add(key);
                            missing.delete(key);
                        }
                    }
                    detectRow.subtitle = `Watching USB devices… ${Math.max(0, Math.ceil(deadline - now))} seconds remaining`;
                    if (now < deadline)
                        return GLib.SOURCE_CONTINUE;
                    this._detectTimer = 0;
                    this._settings.set_double('kvm-detect-until', 0);
                    const found = baseline.filter(d => matches.has(usbKey(d)));
                    const remembered = new Map((config.detected || []).map(d => [usbKey(d), d]));
                    for (const device of found) remembered.set(usbKey(device), device);
                    config.detected = [...remembered.values()];
                    for (const key of matches) detectedKeys.add(key);
                    const selectedKey = config.usb ? usbKey(config.usb) : null;
                    updatingDevices = true;
                    devices = availableDevices();
                    deviceRow.model = Gtk.StringList.new(deviceNames());
                    const candidates = devices.filter(d => matches.has(usbKey(d)));
                    const oldIndex = devices.findIndex(d => usbKey(d) === selectedKey);
                    deviceRow.selected = oldIndex >= 0 ? oldIndex
                        : candidates.length ? devices.indexOf(candidates[0]) : Gtk.INVALID_LIST_POSITION;
                    updatingDevices = false;
                    config.usb = devices[deviceRow.selected] || null;
                    persist();
                    detectRow.subtitle = candidates.length
                        ? `${candidates.length} device(s) disappeared and returned. Choose the KVM device above; selections save automatically.`
                        : 'No matching device found. Try again, staying switched away for at least 5 seconds.';
                    detect.sensitive = true;
                    return GLib.SOURCE_REMOVE;
                });
            });
            dialog.present(this._window);
        });
        deviceRow.connect('notify::selected', () => {
            if (updatingDevices || this._closed || this._kvmGroup !== group) return;
            config.usb = devices[deviceRow.selected] || null;
            persist();
        });
    }

    async _run(...args) {
        try {
            return await run(this.path, ...args);
        } catch (error) {
            const dialog = new Adw.AlertDialog({heading: 'Monitor Presets', body: error.message});
            dialog.add_response('close', 'Close');
            dialog.present(this._window);
            return null;
        }
    }

    async _reload() {
        const state = await this._run('status');
        if (!state)
            return;
        this._loading = true;
        this._presets = state.presets;
        this._fixed.model = Gtk.StringList.new(state.presets.map(p => p.name));
        const selected = state.presets.findIndex(p => p.id === this._settings.get_string('fixed-preset'));
        this._fixed.selected = selected < 0 ? Gtk.INVALID_LIST_POSITION : selected;
        this._loading = false;
        if (this._group)
            this._page.remove(this._group);
        this._group = new Adw.PreferencesGroup({title: 'Saved presets',
            description: 'Order here is the Super+P cycle order.\nDisplays disabled in a preset stay off. Presets that require a missing display cannot be applied.'});
        this._page.add(this._group);
        const moveButtons = [];
        for (const [index, preset] of state.presets.entries()) {
            const expander = new Adw.ExpanderRow({title: preset.name,
                subtitle: preset.unavailable ?? summary(preset.layout), subtitle_lines: 0});
            this._group.add(expander);
            const order = new Gtk.Box({spacing: 6, valign: Gtk.Align.CENTER});
            for (const [icon, label, direction] of [
                ['go-up-symbolic', 'Move Up', -1], ['go-down-symbolic', 'Move Down', 1],
            ]) {
                const button = new Gtk.Button({icon_name: icon, tooltip_text: label,
                    sensitive: index + direction >= 0 && index + direction < state.presets.length});
                button.update_property([Gtk.AccessibleProperty.LABEL], [`${label}: ${preset.name}`]);
                moveButtons.push(button);
                button.connect('clicked', async () => {
                    const enabled = moveButtons.map(b => b.sensitive);
                    for (const b of moveButtons) b.sensitive = false;
                    if (await this._run('move', preset.id, String(direction)))
                        await this._reload();
                    else
                        moveButtons.forEach((b, i) => { b.sensitive = enabled[i]; });
                });
                order.append(button);
            }
            expander.add_suffix(order);
            const name = new Adw.EntryRow({title: 'Name', text: preset.name, show_apply_button: true});
            name.connect('apply', async () => {
                await this._run('rename', preset.id, name.text);
                await this._reload();
            });
            expander.add_row(name);
            const buttons = new Adw.ActionRow({title: 'Manage preset'});
            for (const [label, command, value] of [
                ['Replace with current', 'update', ''], ['Delete', 'delete', '']]) {
                const button = new Gtk.Button({label, valign: Gtk.Align.CENTER});
                if (command === 'delete')
                    button.add_css_class('destructive-action');
                button.connect('clicked', async () => {
                    if (command === 'delete' || command === 'update') {
                        const dialog = new Adw.AlertDialog({heading: command === 'delete'
                            ? `Delete “${preset.name}”?` : `Replace “${preset.name}” with the current layout?`,
                        body: 'This changes the saved preset.'});
                        dialog.add_response('cancel', 'Cancel');
                        dialog.add_response('accept', command === 'delete' ? 'Delete' : 'Replace');
                        dialog.set_response_appearance('accept', Adw.ResponseAppearance.DESTRUCTIVE);
                        dialog.connect('response', async (_dialog, response) => {
                            if (response === 'accept') {
                                await this._run(command, preset.id, value);
                                await this._reload();
                            }
                        });
                        dialog.present(this._window);
                    } else {
                        await this._run(command, preset.id, value);
                        await this._reload();
                    }
                });
                buttons.add_suffix(button);
            }
            expander.add_row(buttons);
        }
        await inputPreferences(this);
    }
}

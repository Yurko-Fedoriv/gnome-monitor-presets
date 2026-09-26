import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as ModalDialog from 'resource:///org/gnome/shell/ui/modalDialog.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as SwitcherPopup from 'resource:///org/gnome/shell/ui/switcherPopup.js';
import {run, count, summary} from './client.js';
import {preview} from './preview.js';
import {MonitorAudio, monitorRow} from './monitorControls.js';
import {KvmWatcher} from './kvm.js';
import {InputShortcuts} from './inputShortcuts.js';

const PresetSwitcher = GObject.registerClass(class PresetSwitcher extends SwitcherPopup.SwitcherPopup {
    _init(presets, active, apply) {
        super._init(presets);
        this._active = active;
        this._apply = apply;
        this._switcherList = new SwitcherPopup.SwitcherList(false);
        for (const preset of presets) {
            const box = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL,
                style_class: 'monitor-preset-tile'});
            box.add_child(preview(preset.layout));
            const label = new St.Label({text: preset.name, x_align: Clutter.ActorAlign.CENTER});
            box.add_child(label);
            box.add_child(new St.Label({text: `${count(preset.layout)} ${count(preset.layout) === 1 ? 'display' : 'displays'}`,
                style_class: 'monitor-preset-caption', x_align: Clutter.ActorAlign.CENTER}));
            this._switcherList.addItem(box, label);
        }
    }

    _initialSelection() {
        const index = this._items.findIndex(p => p.id === this._active);
        this._select((index + 1) % this._items.length);
    }

    _keyPressHandler(key, action) {
        if (action === Meta.KeyBindingAction.SWITCH_MONITOR || key === Clutter.KEY_Right)
            this._select(this._next());
        else if (key === Clutter.KEY_Left)
            this._select(this._previous());
        else
            return Clutter.EVENT_PROPAGATE;
        return Clutter.EVENT_STOP;
    }

    _finish(timestamp) {
        if (this._finished)
            return;
        this._finished = true;
        const selected = this._items[this._selectedIndex];
        super._finish(timestamp);
        this._apply(selected.id);
    }
});

export default class MonitorPresets extends Extension {
    enable() {
        this._enabled = true;
        this._settings = this.getSettings();
        this._monitorAudio = new MonitorAudio(this._settings);
        this._kvmWatcher = new KvmWatcher(this._settings, (...args) => this._command(...args));
        this._nativeSettingSignals = ['restore-at-login', 'startup-policy', 'fixed-preset'].map(key =>
            this._settings.connect(`changed::${key}`, () => this._scheduleNativeSync()));
        this._nativeMonitor = Gio.File.new_for_path(GLib.get_user_config_dir())
            .monitor_directory(Gio.FileMonitorFlags.NONE, null);
        this._nativeMonitor.connect('changed', (_monitor, file, otherFile) => {
            if ([file, otherFile].some(f => f?.get_basename() === 'monitors.xml'))
                this._scheduleNativeSync();
        });
        this._scheduleNativeSync();
        this._indicator = new PanelMenu.Button(0, 'Monitor Presets');
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        box.add_child(new St.Icon({icon_name: 'video-display-symbolic', style_class: 'system-status-icon'}));
        this._number = new St.Label({text: '…', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._number);
        this._indicator.add_child(box);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._indicator.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._refresh();
        });
        this._monitorSignal = Gio.DBus.session.signal_subscribe('org.gnome.Mutter.DisplayConfig',
            'org.gnome.Mutter.DisplayConfig', 'MonitorsChanged', '/org/gnome/Mutter/DisplayConfig',
            null, Gio.DBusSignalFlags.NONE, () => this._refresh());
        Main.wm.setCustomKeybindingHandler('switch-monitor',
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            (_display, _window, _event, binding) => this._showSwitcher(binding));
        this._inputShortcuts = new InputShortcuts(this._settings, (...args) => this._command(...args), this.path, () => this._refresh());
        this._sessionSignal = Main.sessionMode.connect('updated', () => this._sessionUpdated());
        this._sessionUpdated();
        this._command('action-state');
        this._refresh();
        this._startupTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2500, () => {
            this._startupTimer = 0;
            if (!Main.sessionMode.isLocked && this._settings.get_boolean('restore-at-login')) {
                const id = this._settings.get_string('startup-policy') === 'fixed'
                    ? this._settings.get_string('fixed-preset') : 'last';
                this._command('startup', id).then(() => this._refresh());
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _sessionUpdated() {
        const locked = Main.sessionMode.isLocked;
        this._indicator.visible = !locked;
        if (locked) {
            this._indicator.menu.close();
            this._popup?.destroy();
            this._dialog?.destroy();
        } else {
            this._refresh();
        }
    }

    _scheduleNativeSync() {
        if (this._nativeSyncTimer)
            GLib.source_remove(this._nativeSyncTimer);
        this._nativeSyncTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            this._nativeSyncTimer = 0;
            this._command('sync-native');
            return GLib.SOURCE_REMOVE;
        });
    }

    async _command(...args) {
        try {
            const result = await run(this.path, ...args);
            if (this._enabled && result.warnings?.length)
                Main.notify('Monitor Presets — input switching', result.warnings.join('\n'));
            return result;
        } catch (error) {
            if (this._enabled)
                Main.notify('Monitor Presets', error.message);
            return null;
        }
    }

    async _refresh() {
        if (!this._enabled || Main.sessionMode.isLocked)
            return;
        if (this._refreshing) {
            this._refreshAgain = true;
            return;
        }
        this._refreshing = true;
        const state = await this._command('status');
        this._refreshing = false;
        if (!state || !this._enabled || Main.sessionMode.isLocked)
            return;
        this._state = state;
        if (!this._fileMonitor) {
            this._fileMonitor = Gio.File.new_for_path(`${GLib.get_user_config_dir()}/monitor-presets`)
                .monitor_directory(Gio.FileMonitorFlags.NONE, null);
            this._fileMonitor.connect('changed', (_monitor, file, otherFile) => {
                if ([file, otherFile].some(f => ['presets.json', 'pending.json'].includes(f?.get_basename())))
                    this._refresh();
            });
        }
        this._number.text = `${count(state.current)}`;
        this._indicator.accessible_name = `${count(state.current)} active ${count(state.current) === 1 ? 'display' : 'displays'}`;
        const menu = this._indicator.menu;
        menu.removeAll();
        const active = state.presets.find(p => p.id === state.active);
        menu.addMenuItem(new PopupMenu.PopupMenuItem(active?.name ?? 'Custom layout', {reactive: false}));
        const info = new PopupMenu.PopupBaseMenuItem({reactive: false});
        const layoutPreview = preview(state.current, 180, 85);
        layoutPreview.x_expand = true;
        info.add_child(layoutPreview);
        menu.addMenuItem(info);
        const peers = state.current.logical.flatMap(g => g.monitors.map(m => m.spec));
        for (const group of state.current.logical) {
            for (const monitor of group.monitors) {
                const matches = state.ddc.filter(d => d.connector === monitor.spec[0]);
                menu.addMenuItem(monitorRow(this.path, monitor, group,
                    matches.length === 1 ? matches[0] : null, this._monitorAudio, peers));
            }
        }
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        for (const preset of state.presets) {
            const item = new PopupMenu.PopupMenuItem(`${preset.name} · ${count(preset.layout)} ${count(preset.layout) === 1 ? 'display' : 'displays'}`);
            item.setOrnament(preset.id === state.active ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
            // GNOME gives NONE different spacing from DOT. Keep the same icon
            // allocation on every row, but only paint the selected marker.
            item.remove_style_class_name('popup-ornamented-menu-item');
            item._ornamentIcon.icon_name = 'ornament-dot-checked-symbolic';
            item._ornamentIcon.opacity = preset.id === state.active ? 255 : 0;
            item.setSensitive(!preset.unavailable && !state.pending && !this._busy);
            item.connect('activate', () => this._apply('apply', preset.id));
            menu.addMenuItem(item);
        }
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        let actions = [];
        try { actions = JSON.parse(this._settings.get_string('monitor-actions')); } catch (_) { /* Invalid external edit. */ }
        const visible = actions.filter(a => a.outputs?.some(o => o.code));
        for (const action of visible) {
            const item = menu.addAction(action.name || 'Unnamed action', () => this._inputShortcuts.activate(action.id, true));
            item.setSensitive(!state.pending && !this._busy && !this._inputShortcuts?.busy);
        }
        if (visible.length) menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        menu.addAction('Save current layout…', () => this._save());
        const undo = menu.addAction('Restore previous layout', () => this._apply('undo'));
        undo.setSensitive(state.previous && !state.pending && !this._busy);
        if (state.pending)
            menu.addAction('Keep or revert pending change…', () => this._confirm(state.pending));
        menu.addAction('Display Settings', () => {
            Gio.Subprocess.new(['gnome-control-center', 'display'], Gio.SubprocessFlags.NONE);
        });
        menu.addAction('Preset preferences…', () => this.openPreferences());
        if (this._refreshAgain) {
            this._refreshAgain = false;
            this._refresh();
        }
    }

    _showSwitcher(binding) {
        if (Main.sessionMode.isLocked || this._busy || this._popup || this._state?.pending)
            return;
        const presets = this._state?.presets.filter(p => !p.unavailable) ?? [];
        if (!presets.length) {
            Main.notify('Monitor Presets', 'Save your current layout from the display indicator first.');
            return;
        }
        this._popup = new PresetSwitcher(presets, this._state.active, id => this._apply('apply', id));
        this._popup.connect('destroy', () => { this._popup = null; });
        if (!this._popup.show(false, binding.get_name(), binding.get_mask()))
            this._popup.destroy();
    }

    async _apply(...args) {
        if (Main.sessionMode.isLocked || this._busy)
            return;
        this._busy = true;
        const pending = await this._command(args[0], args[1] ?? '',
            this._settings.get_boolean('confirm-layout-changes') ? '' : 'immediate');
        this._busy = false;
        if (!this._enabled || Main.sessionMode.isLocked)
            return;
        if (pending?.token)
            this._confirm(pending);
        this._refresh();
    }

    _confirm(pending) {
        if (Main.sessionMode.isLocked || this._dialog)
            return;
        const dialog = new ModalDialog.ModalDialog();
        this._dialog = dialog;
        const label = new St.Label({text: 'Keep this display layout?'});
        dialog.contentLayout.add_child(label);
        const finish = async command => {
            dialog.close();
            await this._command(command, pending.token);
            this._refresh();
        };
        dialog.setButtons([
            {label: 'Revert', key: Clutter.KEY_Escape, action: () => finish('revert')},
            {label: 'Keep', default: true, action: () => finish('confirm')},
        ]);
        const timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, () => {
            const seconds = Math.ceil(pending.deadline - Date.now() / 1000);
            label.text = `Keep this display layout?\nReverting in ${Math.max(0, seconds)} seconds.`;
            if (seconds <= 0) {
                // The independent helper owns rollback, including if Shell exits.
                dialog.close();
                this._refresh();
            }
            return GLib.SOURCE_CONTINUE;
        });
        dialog.connect('destroy', () => {
            GLib.source_remove(timer);
            this._dialog = null;
        });
        dialog.open();
    }

    _save() {
        if (Main.sessionMode.isLocked || this._dialog)
            return;
        const dialog = new ModalDialog.ModalDialog();
        this._dialog = dialog;
        dialog.contentLayout.add_child(new St.Label({text: 'Save current display layout'}));
        const entry = new St.Entry({hint_text: 'Preset name', can_focus: true});
        dialog.contentLayout.add_child(entry);
        dialog.setInitialKeyFocus(entry.clutter_text);
        dialog.setButtons([
            {label: 'Cancel', key: Clutter.KEY_Escape, action: () => dialog.close()},
            {label: 'Save', default: true, action: async () => {
                const name = entry.get_text().trim();
                if (!name)
                    return;
                dialog.close();
                await this._command('save', name);
                this._refresh();
            }},
        ]);
        dialog.connect('destroy', () => { this._dialog = null; });
        dialog.open();
    }

    disable() {
        // Support unlock-dialog without retaining resources if Shell disables us
        // on a session transition or the user explicitly disables the extension.
        if (this._sessionSignal)
            Main.sessionMode.disconnect(this._sessionSignal);
        this._sessionSignal = 0;
        this._inputShortcuts?.destroy();
        this._inputShortcuts = null;
        this._kvmWatcher?.destroy();
        this._kvmWatcher = null;
        this._enabled = false;
        if (this._nativeSyncTimer)
            GLib.source_remove(this._nativeSyncTimer);
        this._nativeSyncTimer = 0;
        this._nativeMonitor?.cancel();
        this._nativeMonitor = null;
        for (const signal of this._nativeSettingSignals ?? [])
            this._settings.disconnect(signal);
        this._nativeSettingSignals = [];
        if (this._startupTimer)
            GLib.source_remove(this._startupTimer);
        this._startupTimer = 0;
        if (this._monitorSignal)
            Gio.DBus.session.signal_unsubscribe(this._monitorSignal);
        this._monitorSignal = 0;
        this._fileMonitor?.cancel();
        this._fileMonitor = null;
        Main.wm.setCustomKeybindingHandler('switch-monitor',
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW, Main.wm._startSwitcher.bind(Main.wm));
        this._popup?.destroy();
        this._dialog?.destroy();
        this._indicator?.destroy();
        this._indicator = null;
        this._monitorAudio?.destroy();
        this._monitorAudio = null;
        this._state = null;
        this._settings = null;
    }
}

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const ACTION_MODES = Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW |
    Shell.ActionMode.LOCK_SCREEN | Shell.ActionMode.UNLOCK_SCREEN;

export class InputShortcuts {
    constructor(settings, command, path, changed) {
        this.settings = settings;
        this.command = command;
        this.path = path;
        this.changed = changed;
        this.bindings = new Map();
        this.macros = [];
        this.busy = false;
        this.active = true;
        this.signal = settings.connect('changed::monitor-actions', () => { this.reload(); this.changed(); });
        this.acceleratorSignal = global.display.connect('accelerator-activated', (_display, action) => {
            const id = this.bindings.get(action);
            if (id) this.activate(id);
        });
        this.reload();
    }

    async activate(id, fromMenu = false) {
        const modes = ACTION_MODES |
            (fromMenu ? Shell.ActionMode.POPUP : 0);
        if (!this.active || this.busy || (fromMenu && Main.sessionMode.isLocked) || !(Main.actionMode & modes)) return;
        this.busy = true;
        try { await this.command('run-action', id); } finally {
            this.busy = false;
            if (this.active) this.changed();
        }
    }

    clear() {
        for (const action of this.bindings.keys()) {
            Main.wm.allowKeybinding(Meta.external_binding_name_for_action(action), Shell.ActionMode.NONE);
            global.display.ungrab_accelerator(action);
        }
        this.bindings.clear();
        for (const macro of this.macros) { macro.cancel.cancel(); macro.process.force_exit(); }
        this.macros = [];
    }

    watchMacro(entry, trigger) {
        const process = Gio.Subprocess.new(['/usr/bin/python3', `${this.path}/msi.py`, JSON.stringify(trigger.usb)],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        const stream = new Gio.DataInputStream({base_stream: process.get_stdout_pipe()});
        const cancel = new Gio.Cancellable();
        this.macros.push({process, cancel});
        const read = () => stream.read_line_async(GLib.PRIORITY_DEFAULT, cancel, (source, result) => {
            try {
                const [line] = source.read_line_finish_utf8(result);
                if (line === null || cancel.is_cancelled()) return;
                if (JSON.parse(line).pressed) this.activate(entry.id);
                read();
            } catch (error) { if (!cancel.is_cancelled()) console.error(error); }
        });
        read();
    }

    reload() {
        this.clear();
        let entries;
        try { entries = JSON.parse(this.settings.get_string('monitor-actions')); } catch (_) { return; }
        const used = new Set();
        for (const entry of entries) for (const trigger of entry.triggers || []) {
            if (trigger.type === 'msi-macro' && trigger.usb && !used.has('msi-macro')) {
                used.add('msi-macro'); this.watchMacro(entry, trigger); continue;
            }
            if (trigger.type !== 'keyboard' || !trigger.accelerator || used.has(trigger.accelerator)) continue;
            used.add(trigger.accelerator);
            const action = global.display.grab_accelerator(trigger.accelerator, Meta.KeyBindingFlags.IGNORE_AUTOREPEAT);
            if (!action) {
                Main.notify('Monitor Presets', `Cannot register ${trigger.accelerator}: shortcut is already in use or invalid.`);
                continue;
            }
            Main.wm.allowKeybinding(Meta.external_binding_name_for_action(action),
                ACTION_MODES);
            this.bindings.set(action, entry.id);
        }
    }

    destroy() {
        this.active = false;
        this.settings.disconnect(this.signal);
        global.display.disconnect(this.acceleratorSignal);
        this.clear();
    }
}

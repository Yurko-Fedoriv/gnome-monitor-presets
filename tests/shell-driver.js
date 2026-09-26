// Loaded ONLY by smoke-shell.sh in an isolated headless GNOME session.
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const delay = ms => new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
    resolve();
    return GLib.SOURCE_REMOVE;
}));

export default class Driver extends Extension {
    enable() {
        this.exercise().catch(error => this.record({error: error.stack ?? `${error}`}));
    }

    record(data) {
        GLib.file_set_contents(`${GLib.getenv('TEST_ROOT')}/driver-result.json`, JSON.stringify(data));
    }

    async exercise() {
        await delay(1000);
        const extension = Main.extensionManager.lookup('monitor-presets@local').stateObj;
        extension._settings.set_boolean('confirm-layout-changes', true);
        extension._settings.set_string('monitor-actions', JSON.stringify([{id: 'test-action', name: 'Test action',
            outputs: [], preset: null, triggers: [{type: 'keyboard', accelerator: '<Super><Control>F12'}]}]));
        if (extension._inputShortcuts.bindings.size !== 1) throw Error('Action shortcut did not register');
        extension._settings.set_string('monitor-actions', JSON.stringify([
            {id: 'only-preset', name: 'Preset-only action test', outputs: [], triggers: []},
            {id: 'with-input', name: 'Input action test', outputs: [{code: 17, spec: ['Virtual-9', 'TEST', 'Test monitor', 'test'], edid: 'test'}], triggers: []},
        ]));
        await extension._refresh();
        for (let i = 0; i < 60 && extension._refreshing; i++) await delay(50);
        const actionLabels = extension._indicator.menu._getMenuItems().map(item => item.label?.text);
        if (!actionLabels.includes('Input action test') || actionLabels.includes('Preset-only action test'))
            throw Error('Indicator did not filter action menu correctly');
        const shortcuts = extension._inputShortcuts;
        const command = shortcuts.command;
        const calls = [];
        shortcuts.command = async (...args) => { calls.push(args); return {ok: true}; };
        try {
            extension._indicator.menu.open();
            await delay(100);
            await shortcuts.activate('with-input');
            if (calls.length) throw Error('Hardware trigger ran while popup was open');
            const item = extension._indicator.menu._getMenuItems().find(i => i.label?.text === 'Input action test');
            item.emit('activate', null);
            await delay(100);
            if (calls.length !== 1 || calls[0][0] !== 'run-action' || calls[0][1] !== 'with-input')
                throw Error('Open menu action did not invoke the backend exactly once');
        } finally {
            shortcuts.command = command;
            extension._indicator.menu.close();
        }
        // Exercise the real session-mode lifecycle and action gates without
        // locking the user's desktop or depending on test-session PAM setup.
        const watcher = extension._kvmWatcher;
        const actor = new St.Widget({reactive: true});
        Main.uiGroup.add_child(actor);
        Main.sessionMode.pushMode('unlock-dialog');
        await delay(200);
        const grab = Main.pushModal(actor, {actionMode: Shell.ActionMode.UNLOCK_SCREEN});
        const lockedCalls = [];
        const lockedShortcuts = extension._inputShortcuts;
        const lockedCommand = lockedShortcuts.command;
        lockedShortcuts.command = async (...args) => { lockedCalls.push(args); return {ok: true}; };
        try {
            if (!extension._enabled || !Main.sessionMode.isLocked || extension._indicator.visible)
                throw Error('Locked session did not preserve background services and hide the indicator');
            if (extension._kvmWatcher !== watcher)
                throw Error('Lock transition reset the KVM watcher');
            await lockedShortcuts.activate('with-input');
            if (lockedCalls.length !== 1) throw Error('Action rejected in unlock-screen mode');
            await lockedShortcuts.activate('with-input', true);
            if (lockedCalls.length !== 1) throw Error('Menu action permitted while locked');
            extension._showSwitcher({get_name: () => 'switch-monitor', get_mask: () => 0});
            extension._save();
            if (extension._popup || extension._dialog) throw Error('Desktop UI opened while locked');
            const shieldGrab = Main.pushModal(actor, {actionMode: Shell.ActionMode.LOCK_SCREEN});
            try {
                await lockedShortcuts.activate('with-input');
                if (lockedCalls.length !== 2) throw Error('Action rejected in lock-screen mode');
            } finally {
                Main.popModal(shieldGrab);
            }
        } finally {
            lockedShortcuts.command = lockedCommand;
            Main.popModal(grab);
            actor.destroy();
            Main.sessionMode.popMode('unlock-dialog');
        }
        await delay(200);
        if (!extension._indicator.visible || !extension._enabled)
            throw Error('Indicator not restored after unlocking');
        extension._settings.set_string('monitor-actions', '[]');
        if (extension._inputShortcuts.bindings.size !== 0) throw Error('Removed action shortcut stayed registered');

        await extension._refresh();
        if (!extension._state?.presets.length)
            throw new Error('Saved preset missing');
        extension._indicator.menu.open();
        await delay(300);
        extension._indicator.menu.close();
        extension._showSwitcher({get_name: () => 'switch-monitor', get_mask: () => 0});
        await delay(300);
        if (!extension._popup)
            throw new Error('Switcher did not open');
        // Cancel, then exercise selection separately.
        extension._popup._keyPressHandler(Clutter.KEY_Right, 0);
        extension._popup.destroy();
        await extension._apply('apply', extension._state.presets[0].id);
        await delay(400);
        if (!extension._dialog)
            throw new Error('Confirmation dialog did not open');
        const pending = await extension._command('status');
        if (!pending.pending)
            throw new Error('No pending transaction');
        await extension._command('confirm', pending.pending.token);
        extension._dialog.close();
        await delay(300);
        extension._save();
        if (!extension._dialog)
            throw new Error('Save dialog did not open');
        extension._dialog.close();
        await delay(300);
        await extension._apply('undo');
        await delay(300);
        const undo = await extension._command('status');
        if (!undo.pending)
            throw new Error('Undo did not apply');
        await extension._command('revert', undo.pending.token);
        extension._dialog?.close();
        await delay(300);
        extension._settings.set_boolean('confirm-layout-changes', false);
        await extension._apply('apply', extension._state.presets[0].id);
        const immediate = await extension._command('status');
        if (extension._dialog || immediate.pending)
            throw new Error('Immediate apply left a confirmation dialog or pending rollback');
        this.record({ok: true, tested: ['menu and preview', 'switcher', 'apply dialog',
            'confirm', 'save dialog', 'undo', 'revert', 'apply without confirmation']});
    }

    disable() {}
}

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gvc from 'gi://Gvc';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Slider} from 'resource:///org/gnome/shell/ui/slider.js';
import {run} from './client.js';

// A dedicated connection enumerates inactive HDMI ports too, including outputs
// which need a card profile change. Never modify stream volume or software mute.
export class MonitorAudio {
    constructor(settings) {
        this.settings = settings;
        this.devices = new Map();
        this.listeners = new Set();
        this.active = null;
        this.control = new Gvc.MixerControl({name: 'Monitor Presets outputs'});
        this.signals = [
            this.control.connect('output-added', (_c, id) => {
                this.devices.set(id, this.control.lookup_output_id(id));
                this.changed();
            }),
            this.control.connect('output-removed', (_c, id) => {
                this.devices.delete(id);
                this.changed();
            }),
            this.control.connect('active-output-update', (_c, id) => {
                this.active = id;
                this.changed();
            }),
        ];
        this.settingsSignal = settings.connect('changed::monitor-audio-outputs', () => this.changed());
        this.control.open();
    }

    changed() {
        for (const listener of this.listeners) listener();
    }

    key(device) {
        // GVC does not expose a stable card identifier on UI devices. Match
        // the descriptive port tuple, and reject duplicate tuples in resolve().
        return JSON.stringify([device.get_port(), device.get_origin(), device.get_description()]);
    }

    choices() {
        return [...this.devices.values()].filter(d => d && /hdmi|displayport/i.test(
            `${d.get_port()} ${d.get_description()}`));
    }

    saved(spec) {
        try { return JSON.parse(this.settings.get_string('monitor-audio-outputs'))[JSON.stringify(spec.slice(1))]; }
        catch (_) { return null; }
    }

    resolve(spec) {
        const saved = this.saved(spec);
        if (!saved) return null;
        const matches = this.choices().filter(d => this.key(d) === saved);
        return matches.length === 1 ? matches[0] : null;
    }

    destroy() {
        for (const signal of this.signals) this.control.disconnect(signal);
        this.settings.disconnect(this.settingsSignal);
        this.listeners.clear();
        this.control.close();
    }
}

function button(label, icon) {
    return new St.Button({style_class: 'button monitor-control-button', can_focus: true,
        accessible_name: label, child: icon ? new St.Icon({icon_name: icon,
            style_class: 'popup-menu-icon'}) : new St.Label({text: label})});
}

function controlRow() {
    const row = new PopupMenu.PopupBaseMenuItem({reactive: true, activate: false, hover: false, can_focus: false, style_class: 'monitor-control-row'});
    row.remove_style_class_name('popup-inactive-menu-item');
    return row;
}

export function monitorRow(path, monitor, group, capability, audio, command = run) {
    const values = [`${monitor.spec[0]}${group.primary ? '*' : ''}`, `${monitor.width}×${monitor.height}`,
        `${Number(monitor.refresh.toFixed(2))} Hz`, `${Math.round(group.scale * 100)}%`,
        `X: ${group.x}`, `Y: ${group.y}`];
    const item = new PopupMenu.PopupSubMenuMenuItem('');
    item.label.hide();
    item.label_actor = null;
    item.accessible_name = values.join(' · ');
    item.statColumns = values.map(text => new St.Label({text,
        style_class: 'monitor-stat-column', y_align: Clutter.ActorAlign.CENTER}));
    item.statColumns.forEach((label, index) => item.insert_child_at_index(label, index + 1));
    const request = {spec: monitor.spec, edid: capability?.edid};
    let alive = true;
    let generation = 0;
    const timers = new Set();
    const status = new PopupMenu.PopupMenuItem('Discover controls in Preferences → Monitor capabilities', {reactive: false});
    item.menu.addMenuItem(status);
    const hardware = new PopupMenu.PopupMenuSection();
    item.menu.addMenuItem(hardware);
    const output = button('Monitor volume', 'audio-volume-high-symbolic');
    output.add_style_class_name('monitor-control-icon');
    let outputDestroyed = false;
    output.connect('destroy', () => { outputDestroyed = true; });

    const syncAudio = () => {
        if (!alive) return;
        const device = audio.resolve(monitor.spec);
        const active = device && audio.active === device.get_id();
        const configured = !!audio.saved(monitor.spec);
        output.accessible_name = active ? 'Current audio output' : configured ? 'Output here' : 'Monitor volume';
        if (configured) output.add_style_class_name('button');
        else output.remove_style_class_name('button');
        if (active) output.add_style_pseudo_class('checked');
        else output.remove_style_pseudo_class('checked');
        output.reactive = !!device;
        output.can_focus = !!device;
    };
    audio.listeners.add(syncAudio);
    syncAudio();
    output.connect('clicked', () => {
        if (Main.sessionMode.isLocked) return;
        const device = audio.resolve(monitor.spec);
        if (device) audio.control.change_output(device);
    });

    const errorText = error => {
        if (alive) {
            status.label.text = error.message;
            status.actor.show();
        }
    };
    const write = async (feature, value) => {
        if (!alive || !item.menu.isOpen || Main.sessionMode.isLocked) return null;
        status.actor.hide();
        try {
            const result = await command(path, 'set-monitor-control', JSON.stringify({...request, feature, value}));
            if (capability) capability.controls[feature] = result.control;
            return result;
        } catch (error) {
            errorText(error);
            return null;
        }
    };
    const populate = controls => {
        hardware.removeAll();
        const version = ++generation;
        let volumeRow = null;
        let volumeAction = null;
        for (const [feature, icon, title] of [
            ['brightness', 'display-brightness-symbolic', 'Monitor brightness'],
            ['volume', 'audio-volume-high-symbolic', 'Monitor volume'],
        ]) {
            const state = controls[feature];
            if (!state) continue;
            const row = controlRow();
            const leading = new St.Bin({style_class: 'monitor-control-slot'});
            leading.child = feature === 'volume' ? output : new St.Icon({icon_name: icon, style_class: 'popup-menu-icon', accessible_name: title});
            row.add_child(leading);
            const slider = new Slider(state.value / state.maximum);
            slider.x_expand = true;
            slider.accessible_name = title;
            row.add_child(slider);
            const label = new St.Label({text: `${Math.round(slider.value * 100)}%`,
                y_align: Clutter.ActorAlign.CENTER, style_class: 'monitor-control-value'});
            row.add_child(label);
            const trailing = new St.Bin({style_class: 'monitor-control-slot'});
            row.add_child(trailing);
            hardware.addMenuItem(row);
            if (feature === 'volume') { volumeRow = row; volumeAction = trailing; }
            let timer = 0;
            let busy = false;
            let wanted = null;
            let updating = false;
            const flush = async () => {
                if (busy || wanted === null || version !== generation) return;
                busy = true;
                const value = wanted;
                wanted = null;
                const result = await write(feature, value);
                busy = false;
                if (!alive || version !== generation) return;
                if (wanted !== null) { flush(); return; }
                updating = true;
                // Restore the last confirmed value after a failed write.
                if (result) state.value = result.control.value;
                slider.value = state.value / state.maximum;
                label.text = `${Math.round(slider.value * 100)}%`;
                updating = false;
            };
            slider.connect('notify::value', () => {
                label.text = `${Math.round(slider.value * 100)}%`;
                if (updating) return;
                wanted = Math.round(slider.value * state.maximum);
                if (timer) { GLib.source_remove(timer); timers.delete(timer); }
                timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
                    timers.delete(timer);
                    timer = 0;
                    flush();
                    return GLib.SOURCE_REMOVE;
                });
                timers.add(timer);
            });
        }
        if (!volumeRow && (controls.mute || audio.saved(monitor.spec))) {
            volumeRow = controlRow();
            volumeRow.add_child(new St.Bin({style_class: 'monitor-control-slot', child: output}));
            volumeRow.add_child(new St.Label({text: 'Monitor audio', x_expand: true, y_align: Clutter.ActorAlign.CENTER}));
            volumeAction = new St.Bin({style_class: 'monitor-control-slot'});
            volumeRow.add_child(volumeAction);
            hardware.addMenuItem(volumeRow);
        }
        if (controls.mute) {
            let muted = controls.mute.value;
            const mute = button('Mute monitor', 'audio-volume-muted-symbolic');
            const sync = () => {
                mute.accessible_name = muted ? 'Unmute monitor' : 'Mute monitor';
                if (muted) mute.add_style_pseudo_class('checked');
                else mute.remove_style_pseudo_class('checked');
            };
            sync();
            volumeAction.child = mute;
            mute.connect('clicked', async () => {
                mute.reactive = false;
                const result = await write('mute', !muted);
                if (!alive || version !== generation) return;
                if (result) muted = result.control.value;
                mute.reactive = true;
                sync();
            });
        }
    };
    const savedControls = capability?.controls ?? {};
    populate(JSON.parse(JSON.stringify(savedControls)));
    status.visible = !Object.keys(savedControls).length;
    if (capability?.controls_probed && !Object.keys(savedControls).length)
        status.label.text = 'No supported monitor controls discovered';
    item.connect('destroy', () => {
        alive = false;
        generation++;
        for (const timer of timers) GLib.source_remove(timer);
        timers.clear();
        audio.listeners.delete(syncAudio);
        if (!outputDestroyed) output.destroy();
    });
    return item;
}

// Use one measured width per column across all rows, including after theme or
// font changes. Spaces in a single label cannot align proportional text.
export function alignMonitorRows(rows) {
    let updating = false;
    const align = () => {
        if (updating || !rows.length) return;
        updating = true;
        for (const row of rows) for (const label of row.statColumns) label.width = -1;
        const widths = rows[0].statColumns.map((_label, column) =>
            Math.max(...rows.map(row => row.statColumns[column].get_preferred_width(-1)[1])));
        for (const row of rows)
            row.statColumns.forEach((label, column) => { label.width = widths[column]; });
        updating = false;
    };
    for (const row of rows) {
        row.connect('destroy', () => { const index = rows.indexOf(row); if (index >= 0) rows.splice(index, 1); });
        row.connect('notify::mapped', () => { if (row.mapped) align(); });
        row.connect('style-changed', align);
    }
    align();
}

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

    resolve(spec, peers) {
        const choices = this.choices();
        const saved = this.saved(spec);
        if (saved) {
            const matches = choices.filter(d => this.key(d) === saved);
            return matches.length === 1 ? matches[0] : null;
        }
        if (peers.filter(s => s[2] === spec[2]).length !== 1) return null;
        const matches = choices.filter(d => `${d.get_description()} ${d.get_origin()}`.includes(spec[2]));
        return matches.length === 1 ? matches[0] : null;
    }

    assign(spec, device) {
        let saved;
        try { saved = JSON.parse(this.settings.get_string('monitor-audio-outputs')); } catch (_) { saved = {}; }
        saved[JSON.stringify(spec.slice(1))] = this.key(device);
        this.settings.set_string('monitor-audio-outputs', JSON.stringify(saved));
        this.changed();
    }

    destroy() {
        for (const signal of this.signals) this.control.disconnect(signal);
        this.listeners.clear();
        this.control.close();
    }
}

function button(label, icon) {
    return new St.Button({style_class: 'button monitor-control-button', can_focus: true,
        accessible_name: label, child: icon ? new St.Icon({icon_name: icon,
            style_class: 'popup-menu-icon'}) : new St.Label({text: label})});
}

export function monitorRow(path, monitor, group, ddc, audio, peers, command = run) {
    const text = `${monitor.spec[0]}${group.primary ? '*' : ''}   ${monitor.width}×${monitor.height}` +
        `   ${Number(monitor.refresh.toFixed(2))} Hz   ${Math.round(group.scale * 100)}%` +
        `   X: ${group.x}   Y: ${group.y}`;
    const item = new PopupMenu.PopupSubMenuMenuItem(text);
    const request = {spec: monitor.spec, edid: ddc?.edid};
    let alive = true;
    let loading = false;
    let generation = 0;
    const timers = new Set();
    const status = new PopupMenu.PopupMenuItem('Open to read monitor controls', {reactive: false});
    item.menu.addMenuItem(status);
    const hardware = new PopupMenu.PopupMenuSection();
    item.menu.addMenuItem(hardware);
    const audioRow = new PopupMenu.PopupBaseMenuItem({reactive: false});
    const output = button('Output here');
    const choose = button('Choose monitor audio output', 'pan-down-symbolic');
    audioRow.add_child(output);
    audioRow.add_child(choose);
    item.menu.addMenuItem(audioRow);
    const outputs = new PopupMenu.PopupMenuSection();
    outputs.actor.hide();
    item.menu.addMenuItem(outputs);

    const syncAudio = () => {
        if (!alive) return;
        const device = audio.resolve(monitor.spec, peers);
        const active = device && audio.active === device.get_id();
        output.child.text = active ? '✓ Output here' : 'Output here';
        output.accessible_name = active ? 'Current audio output' : 'Output here';
        if (active) output.add_style_pseudo_class('checked');
        else output.remove_style_pseudo_class('checked');
        output.reactive = !!device;
        output.can_focus = !!device;
        outputs.removeAll();
        const devices = audio.choices();
        outputs.addMenuItem(new PopupMenu.PopupMenuItem(`Audio output for ${monitor.spec[0]}`, {reactive: false}));
        if (!devices.length)
            outputs.addMenuItem(new PopupMenu.PopupMenuItem('No monitor audio outputs available', {reactive: false}));
        for (const candidate of devices) {
            const name = [candidate.get_description(), candidate.get_origin()].filter(Boolean).join(' — ');
            const option = new PopupMenu.PopupMenuItem(name);
            option.setOrnament(device?.get_id() === candidate.get_id()
                ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
            option.connect('activate', () => {
                audio.assign(monitor.spec, candidate);
                outputs.actor.hide();
            });
            outputs.addMenuItem(option);
        }
    };
    audio.listeners.add(syncAudio);
    syncAudio();
    choose.connect('clicked', () => {
        syncAudio();
        outputs.actor.visible = !outputs.actor.visible;
    });
    output.connect('clicked', () => {
        if (Main.sessionMode.isLocked) return;
        const device = audio.resolve(monitor.spec, peers);
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
            return await command(path, 'set-monitor-control', JSON.stringify({...request, feature, value}));
        } catch (error) {
            errorText(error);
            return null;
        }
    };
    const populate = controls => {
        hardware.removeAll();
        const version = ++generation;
        let volumeRow = null;
        for (const [feature, icon, title] of [
            ['brightness', 'display-brightness-symbolic', 'Monitor brightness'],
            ['volume', 'audio-volume-high-symbolic', 'Monitor volume'],
        ]) {
            const state = controls[feature];
            if (!state) continue;
            const row = new PopupMenu.PopupBaseMenuItem({reactive: false});
            row.add_child(new St.Icon({icon_name: icon, style_class: 'popup-menu-icon', accessible_name: title}));
            const slider = new Slider(state.value / state.maximum);
            slider.x_expand = true;
            slider.accessible_name = title;
            row.add_child(slider);
            const label = new St.Label({text: `${Math.round(slider.value * 100)}%`,
                y_align: Clutter.ActorAlign.CENTER, style_class: 'monitor-control-value'});
            row.add_child(label);
            hardware.addMenuItem(row);
            if (feature === 'volume') volumeRow = row;
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
        if (controls.mute) {
            const row = volumeRow ?? new PopupMenu.PopupBaseMenuItem({reactive: false});
            if (!volumeRow) hardware.addMenuItem(row);
            let muted = controls.mute.value;
            const mute = button('Mute monitor', 'audio-volume-muted-symbolic');
            const sync = () => {
                mute.accessible_name = muted ? 'Unmute monitor' : 'Mute monitor';
                if (muted) mute.add_style_pseudo_class('checked');
                else mute.remove_style_pseudo_class('checked');
            };
            sync();
            row.add_child(mute);
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
    item.menu.connect('open-state-changed', async (_menu, open) => {
        if (!open || loading) return;
        loading = true;
        status.label.text = 'Reading monitor controls…';
        status.actor.show();
        hardware.removeAll();
        generation++;
        try {
            const result = await command(path, 'monitor-controls', JSON.stringify(request));
            if (!alive) return;
            populate(result.controls);
            status.label.text = 'Monitor controls unavailable';
            status.actor.visible = !Object.keys(result.controls).length;
        } catch (error) {
            errorText(error);
        } finally {
            loading = false;
        }
    });
    item.connect('destroy', () => {
        alive = false;
        generation++;
        for (const timer of timers) GLib.source_remove(timer);
        timers.clear();
        audio.listeners.delete(syncAudio);
    });
    return item;
}

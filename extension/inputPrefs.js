import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gtk from 'gi://Gtk';
import GLib from 'gi://GLib';
import {monitorName} from './monitorNames.js';
import {fullValueCombo} from './preferencesWidgets.js';

const same = (a, b) => JSON.stringify(a?.slice(1)) === JSON.stringify(b?.slice(1));

export async function inputPreferences(owner) {
    owner._clearCapabilityAudio?.();
    for (const key of ['_inputGroup', '_actionGroup']) if (owner[key]) owner._page.remove(owner[key]);
    const state = await owner._run('action-state');
    const initial = await owner._run('monitor-capabilities');
    if (!state || !initial || owner._closed) return;
    let actions = state.actions;
    let targets = initial.targets;
    let audioOutputs = initial.audio_outputs ?? [];
    let audioError = initial.audio_error;
    const save = () => owner._settings.set_string('monitor-actions', JSON.stringify(actions));
    const alert = message => {
        const dialog = new Adw.AlertDialog({heading: 'Monitor actions', body: message});
        dialog.add_response('close', 'Close'); dialog.present(owner._window);
    };
    const discovery = new Adw.PreferencesGroup({title: 'Monitor capabilities',
        description: 'Control each monitor’s own input, brightness, volume and mute, where supported. Activate connected monitors before discovering their capabilities.'});
    owner._inputGroup = discovery;
    owner._page.add(discovery);
    const refresh = new Gtk.Button({label: 'Discover capabilities', valign: Gtk.Align.CENTER});
    discovery.header_suffix = refresh;
    const displayRows = [];
    const expanded = new Map();
    const actionRefreshers = [];
    const audioRefreshers = [];
    const assignments = () => {
        try { return JSON.parse(owner._settings.get_string('monitor-audio-outputs')); }
        catch (_) { return {}; }
    };
    let audioUpdate = 0;
    const updateAudioChoices = () => {
        // Replacing a ComboRow model from its own notify::selected callback
        // can dispose GTK's selection model while the setter is still running.
        if (audioUpdate) return;
        audioUpdate = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            audioUpdate = 0;
            for (const update of audioRefreshers) update();
            return GLib.SOURCE_REMOVE;
        });
    };
    const audioSignal = owner._settings.connect('changed::monitor-audio-outputs', updateAudioChoices);
    owner._clearCapabilityAudio = () => {
        owner._settings.disconnect(audioSignal);
        if (audioUpdate) GLib.source_remove(audioUpdate);
        audioUpdate = 0;
        audioRefreshers.length = 0;
        owner._clearCapabilityAudio = null;
    };
    const showDisplays = () => {
        audioRefreshers.length = 0;
        for (const row of displayRows) discovery.remove(row);
        displayRows.length = 0;
        for (const target of targets) {
            const subtitle = () => target.inputs.map(i => i.label).join(' · ') + (!target.edid ? ' · disconnected' : '');
            const identity = JSON.stringify(target.spec.slice(1));
            const row = new Adw.ExpanderRow({title: monitorName(target.spec, target.connector), tooltip_text: target.spec[2],
                subtitle: subtitle(), expanded: expanded.get(identity) ?? false});
            row.connect('notify::expanded', () => expanded.set(identity, row.expanded));
            const detected = Object.keys(target.controls ?? {});
            if (target.inputs.length) detected.unshift('input');
            if (target.controls_probed || detected.length) {
                const labels = {input: 'Input switching', brightness: 'Brightness', volume: 'Volume', mute: 'Mute'};
                row.add_row(new Adw.ActionRow({title: `Hardware controls: ${detected.map(key => labels[key] ?? key).join(' · ') || 'None detected'}`,
                    title_lines: 0}));
            }
            for (const option of target.options || []) {
                if (option.type !== 'boolean') continue;
                const optionRow = new Adw.ActionRow({title: option.label, subtitle: option.tooltip, subtitle_lines: 0});
                const toggle = new Gtk.Switch({active: option.value, valign: Gtk.Align.CENTER});
                toggle.update_property([Gtk.AccessibleProperty.LABEL], [option.label]);
                let changing = false;
                toggle.connect('notify::active', async () => {
                    if (changing) return;
                    toggle.sensitive = false;
                    const was = target.options.find(o => o.key === option.key)?.value ?? option.value;
                    const result = await owner._run('monitor-profile', JSON.stringify({spec: target.spec, [option.key]: toggle.active}));
                    if (owner._closed) return;
                    const updated = result?.targets.find(t => same(t.spec, target.spec));
                    if (updated) { Object.assign(target, updated); row.subtitle = subtitle(); for (const update of actionRefreshers) update(); }
                    else { changing = true; toggle.active = was; changing = false; }
                    toggle.sensitive = true;
                });
                optionRow.add_suffix(toggle);
                optionRow.activatable_widget = toggle;
                row.add_row(optionRow);
            }
            const output = fullValueCombo({title: 'Audio output',
                subtitle: audioError ? 'Audio outputs unavailable; saved association retained' : 'Choose the sound output activated by this monitor’s speaker button.'});
            let choices = [];
            let updating = false;
            const updateOutput = () => {
                const saved = assignments();
                const selected = saved[identity];
                const used = new Set(Object.entries(saved).filter(([key]) => key !== identity).map(([, value]) => value));
                const previous = choices;
                choices = [{key: null, label: 'Not assigned'},
                    ...audioOutputs.filter(choice => choice.key === selected || !used.has(choice.key))];
                if (selected && !choices.some(c => c.key === selected)) {
                    let label = 'Saved output';
                    try { const parts = JSON.parse(selected); label = [parts[2], parts[1]].filter(Boolean).join(' — '); } catch (_) { /* Keep unknown saved values. */ }
                    choices.push({key: selected, label: `${label} (unavailable)`});
                }
                updating = true;
                if (JSON.stringify(previous) !== JSON.stringify(choices))
                    output.model = Gtk.StringList.new(choices.map(c => c.label));
                output.selected = Math.max(0, choices.findIndex(c => c.key === selected));
                updating = false;
            };
            updateOutput();
            audioRefreshers.push(updateOutput);
            output.connect('notify::selected', () => {
                if (updating) return;
                const saved = assignments();
                const selected = choices[output.selected]?.key;
                if (selected && Object.entries(saved).some(([key, value]) => key !== identity && value === selected)) {
                    updateAudioChoices();
                    return;
                }
                if (selected) saved[identity] = selected;
                else delete saved[identity];
                owner._settings.set_string('monitor-audio-outputs', JSON.stringify(saved));
            });
            row.add_row(output);
            discovery.add(row); displayRows.push(row);
        }
    };
    showDisplays();
    refresh.connect('clicked', async () => {
        refresh.sensitive = false;
        const result = await owner._run('refresh-monitor-capabilities');
        if (owner._closed) return;
        refresh.sensitive = true;
        if (!result) return;
        targets = result.targets;
        audioOutputs = result.audio_outputs ?? audioOutputs;
        audioError = result.audio_error;
        showDisplays();
        for (const update of actionRefreshers) update();
        if (result.warnings.length) alert(result.warnings.join('\n'));
    });
    await owner._reloadKvm();
    const group = new Adw.PreferencesGroup({title: 'Actions',
        description: 'Each trigger runs one named action. Choose a preset, monitor inputs, or both. Unavailable monitors are skipped quietly. An action-induced KVM disconnect is suppressed once.'});
    owner._actionGroup = group;
    owner._page.add(group);
    const add = new Gtk.Button({label: '+ Add', valign: Gtk.Align.CENTER});
    group.header_suffix = add;
    const capture = (action, done) => {
        const window = new Adw.Window({title: 'Choose shortcut', modal: true, transient_for: owner._window,
            default_width: 440, default_height: 170});
        const label = new Gtk.Label({label: 'Press a shortcut with Super, Ctrl or Alt.\nEscape cancels.', wrap: true,
            margin_top: 24, margin_bottom: 24, margin_start: 24, margin_end: 24});
        const key = new Gtk.EventControllerKey();
        key.connect('key-pressed', (_controller, value, _code, state) => {
            if (value === Gdk.KEY_Escape) { window.close(); return true; }
            const mods = (state & Gtk.accelerator_get_default_mod_mask()) & ~Gdk.ModifierType.LOCK_MASK;
            if (!(mods & (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK)) || !Gtk.accelerator_valid(value, mods)) return true;
            const accelerator = Gtk.accelerator_name(Gdk.keyval_to_lower(value), mods);
            if (actions.some(a => a.triggers.some(t => t.type === 'keyboard' && t.accelerator === accelerator))) {
                label.label = 'This shortcut already belongs to an action.'; return true;
            }
            action.triggers.push({type: 'keyboard', accelerator}); save(); done(); window.close(); return true;
        });
        window.add_controller(key); window.set_content(label);
        window.connect('map', () => window.get_surface()?.inhibit_system_shortcuts(null));
        window.connect('close-request', () => { window.get_surface()?.restore_system_shortcuts(); return false; });
        window.present();
    };
    const triggerName = trigger => {
        if (trigger.type === 'kvm') return 'KVM disconnect';
        if (trigger.type === 'msi-macro') return 'MSI Macro Key';
        const [ok, key, mods] = Gtk.accelerator_parse(trigger.accelerator || '');
        return ok ? Gtk.accelerator_get_label(key, mods) : 'Keyboard shortcut';
    };
    const addAction = action => {
        const expander = new Adw.ExpanderRow({title: action.name, subtitle: 'No triggers', expanded: false});
        const name = new Adw.EntryRow({title: 'Action name', text: action.name});
        name.connect('notify::text', () => { action.name = name.text; expander.title = action.name || 'Unnamed action'; save(); });
        expander.add_row(name);
        const triggerRows = [];
        const triggerList = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 6});
        const rebuildTriggers = () => {
            for (const row of triggerRows) triggerList.remove(row);
            triggerRows.length = 0;
            expander.subtitle = action.triggers.map(triggerName).join(' · ') || 'No triggers';
            for (const trigger of action.triggers) {
                const row = new Gtk.Box({spacing: 6});
                row.append(new Gtk.Label({label: triggerName(trigger), hexpand: true, xalign: 0}));
                const remove = new Gtk.Button({icon_name: 'list-remove-symbolic', valign: Gtk.Align.CENTER, tooltip_text: 'Remove trigger'});
                remove.connect('clicked', () => { action.triggers = action.triggers.filter(t => t !== trigger); save(); rebuildTriggers(); });
                row.append(remove); triggerList.append(row); triggerRows.push(row);
            }
        };
        const triggerRow = new Adw.ActionRow({title: 'Triggers'});
        const triggerMenu = new Gtk.MenuButton({label: '+ Add trigger', valign: Gtk.Align.CENTER});
        const popover = new Gtk.Popover();
        const choices = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 6, margin_top: 6, margin_bottom: 6, margin_start: 6, margin_end: 6});
        for (const [title, type] of [['Keyboard shortcut', 'keyboard'], ['KVM disconnect', 'kvm'], ['MSI Macro Key', 'msi-macro']]) {
            const button = new Gtk.Button({label: title});
            button.connect('clicked', () => {
                popover.popdown();
                if (type === 'keyboard') { capture(action, rebuildTriggers); return; }
                if (actions.some(a => a.triggers.some(t => t.type === type))) { alert(`${title} is already assigned. Remove it from its current action first.`); return; }
                const trigger = {type};
                if (type === 'msi-macro') {
                    if (state.controllers.length !== 1 || !state.controllers[0].accessible) {
                        alert('Connect one MSI monitor controller and enable its USB access using hardware/enable-msi-access.sh. Then reopen preferences.'); return;
                    }
                    trigger.usb = state.controllers[0];
                }
                action.triggers.push(trigger); save(); rebuildTriggers();
            });
            choices.append(button);
        }
        popover.set_child(choices); triggerMenu.popover = popover;
        const triggerControls = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 6,
            margin_top: 8, margin_bottom: 8});
        triggerControls.append(triggerList); triggerControls.append(triggerMenu);
        triggerRow.add_suffix(triggerControls); expander.add_row(triggerRow);
        const presets = [null, ...owner._presets];
        const preset = fullValueCombo({title: 'Display preset', model: Gtk.StringList.new(['Keep current', ...owner._presets.map(p => p.name)]),
            selected: Math.max(0, presets.findIndex(p => p?.id === action.preset))});
        expander.add_row(preset);
        let monitorRows = [];
        const updateWarnings = () => {
            const layout = owner._presets.find(p => p.id === action.preset)?.layout;
            const active = layout?.logical.flatMap(g => g.monitors.map(m => m.spec)) || [];
            for (const {row, target} of monitorRows) {
                const redirected = action.outputs.some(o => same(o.spec, target.spec));
                row.subtitle = redirected && active.some(spec => same(spec, target.spec))
                    ? '⚠ Enabled by this preset, but redirected by this action' : '';
            }
        };
        const updateMonitors = () => {
            for (const {row} of monitorRows) expander.remove(row);
            monitorRows = [];
            const known = [...targets];
            for (const output of action.outputs) if (!known.some(t => same(t.spec, output.spec)))
                known.push({spec: output.spec, connector: output.spec[0], inputs: []});
            for (const target of known) {
                const previous = action.outputs.find(o => same(o.spec, target.spec));
                const codes = [null, ...target.inputs.map(i => i.code)];
                const labels = ['Stay on current input', ...target.inputs.map(i => i.label)];
                if (previous?.code && !codes.includes(previous.code)) {
                    codes.push(previous.code); labels.push(`Saved input 0x${previous.code.toString(16)}`);
                }
                const row = fullValueCombo({title: monitorName(target.spec, target.connector), tooltip_text: target.spec[2],
                    model: Gtk.StringList.new(labels), selected: Math.max(0, codes.indexOf(previous?.code))});
                row.connect('notify::selected', () => {
                    const code = codes[row.selected];
                    action.outputs = action.outputs.filter(o => !same(o.spec, target.spec));
                    if (code) action.outputs.push({spec: target.spec, edid: target.edid || previous?.edid, code});
                    save(); updateWarnings();
                });
                expander.add_row(row); monitorRows.push({row, target});
            }
            updateWarnings();
        };
        actionRefreshers.push(updateMonitors);
        preset.connect('notify::selected', () => { action.preset = presets[preset.selected]?.id || null; save(); updateWarnings(); });
        const removeRow = new Adw.ActionRow({title: 'Delete action'});
        const remove = new Gtk.Button({icon_name: 'edit-delete-symbolic', valign: Gtk.Align.CENTER, tooltip_text: 'Delete action'});
        remove.connect('clicked', () => {
            actions = actions.filter(a => a.id !== action.id);
            actionRefreshers.splice(actionRefreshers.indexOf(updateMonitors), 1);
            group.remove(expander); save();
        });
        removeRow.add_suffix(remove);
        rebuildTriggers(); updateMonitors(); expander.add_row(removeRow); group.add(expander);
        return expander;
    };
    for (const action of actions) addAction(action);
    add.connect('clicked', () => {
        let n = 1;
        while (actions.some(a => a.name === `Action ${n}`)) n++;
        const name = new Gtk.Entry({text: `Action ${n}`, activates_default: true});
        const dialog = new Adw.AlertDialog({heading: 'New action', extra_child: name,
            default_response: 'add', close_response: 'cancel'});
        dialog.add_response('cancel', 'Cancel'); dialog.add_response('add', 'Add');
        dialog.set_response_appearance('add', Adw.ResponseAppearance.SUGGESTED);
        dialog.connect('response', (_dialog, response) => {
            if (response !== 'add' || owner._closed) return;
            const action = {id: GLib.uuid_string_random(), name: name.text.trim() || `Action ${n}`,
                preset: null, outputs: [], triggers: []};
            actions.push(action); addAction(action).expanded = true; save();
        });
        dialog.present(owner._window); name.grab_focus(); name.select_region(0, -1);
    });
}

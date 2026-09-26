import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import GLib from 'gi://GLib';
import {inputPreferences} from '../extension/inputPrefs.js';

Adw.init();
const project = GLib.getenv('PROJECT');
const [, bytes] = Gio.File.new_for_path(`${project}/extension/prefs.js`).load_contents(null);
const source = new TextDecoder().decode(bytes)
    .replace(/import \{ExtensionPreferences\} from .*;/, 'class ExtensionPreferences {}')
    .replaceAll("from './", `from 'file://${project}/extension/`);
const temporary = GLib.dir_make_tmp('monitor-preferences-test-XXXXXX');
const module = `${temporary}/prefs.js`;
GLib.file_set_contents(module, source);
function find(widget, title) {
    if (widget.get_title?.() === title ||
        (title === 'USB device to watch' && widget.get_name() === 'usb-device-to-watch')) return widget;
    for (let child = widget.get_first_child(); child; child = child.get_next_sibling()) {
        const found = find(child, title); if (found) return found;
    }
    return null;
}
function childType(widget, type) {
    if (widget instanceof type) return widget;
    for (let child = widget.get_first_child(); child; child = child.get_next_sibling()) {
        const found = childType(child, type); if (found) return found;
    }
    return null;
}
try {
    const {default: Preferences} = await import(`file://${module}`);
    const p = new Preferences();
    p._settings = Gio.Settings.new('org.gnome.shell.extensions.monitor-presets');
    p._page = new Adw.PreferencesPage();
    p._window = new Adw.PreferencesWindow(); p._window.add(p._page);
    const spec = ['HDMI-1', 'GSM', 'LG HDR 4K', 'test'];
    p._presets = [{id: 'center', name: 'Center', layout: {logical: []}},
        {id: 'all', name: 'All', layout: {logical: [{monitors: [{spec}]}]}}];
    p._settings.set_string('kvm-config', JSON.stringify({usb: {vendor: 'ffff', product: 'ffff', name: 'Test device'},
        detected: [{vendor: 'ffff', product: 'ffff', name: 'Test device'}]}));
    p._settings.set_string('monitor-actions', JSON.stringify([{id: 'a', name: 'Action 1', preset: null,
        outputs: [{spec, edid: 'test-edid', code: 15}], triggers: []}]));
    const target = {spec, connector: 'HDMI-1', edid: 'test-edid', usb_c: true,
        options: [{key: 'usb_c', type: 'boolean', label: 'Has Type-C', value: true, tooltip: 'Test option'}],
        inputs: [{code: 15, label: 'DisplayPort'}, {code: 16, label: 'USB-C'}]};
    p._run = async command => command === 'action-state'
        ? {actions: JSON.parse(p._settings.get_string('monitor-actions')), controllers: []}
        : {targets: [JSON.parse(JSON.stringify(target))], updated: 1, warnings: []};
    const originalRun = p._run;
    await inputPreferences(p);
    const usbRow = find(p._page, 'USB device to watch');
    if (!usbRow.model.get_string(0).startsWith('Detected · Test device') || usbRow.selected !== 0)
        throw Error('Remembered USB detection was not restored');
    p._window.present(); usbRow.activate();
    await new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => { resolve(); return GLib.SOURCE_REMOVE; }));
    const marks = [];
    const collect = widget => {
        if (widget instanceof Gtk.Image && widget.icon_name === 'object-select-symbolic') marks.push(widget);
        for (let c = widget.get_first_child(); c; c = c.get_next_sibling()) collect(c);
    };
    collect(usbRow);
    if (!marks.some(m => m.opacity === 1)) throw Error('Missing selected USB marker');
    const discoveryRow = find(p._inputGroup, 'HDMI-1 · LG HDR 4K');
    const toggle = childType(discoveryRow, Gtk.Switch);
    let finish;
    p._run = () => new Promise(resolve => { finish = resolve; });
    toggle.active = false;
    if (find(p._inputGroup, 'HDMI-1 · LG HDR 4K') !== discoveryRow) throw Error('Toggle collapsed discovery');
    finish({targets: [{...target, usb_c: false, options: [{...target.options[0], value: false}], inputs: [{code: 15, label: 'DisplayPort'}]}]});
    await Promise.resolve();
    if (find(p._inputGroup, 'HDMI-1 · LG HDR 4K') !== discoveryRow) throw Error('Toggle replaced discovery row');
    toggle.active = true; finish(null); await Promise.resolve();
    if (toggle.active || !toggle.sensitive) throw Error('Failed toggle not restored');
    p._run = originalRun;
    toggle.active = true; await Promise.resolve();
    const expander = find(p._actionGroup, 'Action 1');
    const destination = find(expander, 'HDMI-1 · LG HDR 4K');
    destination.selected = 2;
    const config = () => JSON.parse(p._settings.get_string('monitor-actions'))[0];
    if (config().outputs[0].code !== 16) throw Error('Action destination not autosaved');
    find(expander, 'Display preset').selected = 2;
    if (!destination.subtitle.includes('Enabled by this preset') || config().outputs[0].code !== 16)
        throw Error('Preset conflict should warn, not remove redirect');
    await inputPreferences(p);
    if (find(find(p._actionGroup, 'Action 1'), 'HDMI-1 · LG HDR 4K').selected !== 2)
        throw Error('Action destination not restored');
    const before = find(p._inputGroup, 'HDMI-1 · LG HDR 4K');
    p._run = () => new Promise(resolve => { finish = resolve; });
    p._inputGroup.header_suffix.emit('clicked');
    if (find(p._inputGroup, 'HDMI-1 · LG HDR 4K') !== before) throw Error('Refresh collapsed discovery during query');
    finish(null); await Promise.resolve();
    if (find(p._inputGroup, 'HDMI-1 · LG HDR 4K') !== before) throw Error('Failed refresh lost discovery');
    p._actionGroup.header_suffix.emit('clicked');
    const naming = p._window.get_visible_dialog();
    if (!naming || naming.extra_child.text !== 'Action 2') throw Error('New action did not ask for a default name');
    naming.emit('response', 'add'); naming.close();
    if (!JSON.parse(p._settings.get_string('monitor-actions')).some(a => a.name === 'Action 2'))
        throw Error('Named action was not saved');
    p._closed = true; p._clearDeviceRow();
    p._window.destroy();
    print('PASS: remembered USB selection, stable discovery, action autosave, preset conflict warning and reopen');
} finally { GLib.unlink(module); GLib.rmdir(temporary); }

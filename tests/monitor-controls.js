import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

export async function exerciseControls(extension, delay) {
    const {monitorRow, MonitorAudio} = await import(`file://${extension.path}/monitorControls.js`);
    const spec = ['HDMI-1', 'GSM', 'LG HDR 4K', 'test'];
    const device = {get_id: () => 42, get_description: () => 'LG HDR 4K', get_origin: () => 'HDMI 1'};
    let selected = 0;
    const audio = {listeners: new Set(), active: 42, resolve: () => device,
        choices: () => [device], control: {change_output: () => selected++}};
    const calls = [];
    const states = {brightness: {value: 80, maximum: 100}, volume: {value: 40, maximum: 100}, mute: {value: true}};
    const command = async (_path, action, json) => {
        const request = JSON.parse(json);
        calls.push([action, request]);
        if (action === 'monitor-controls') return {controls: JSON.parse(JSON.stringify(states))};
        states[request.feature].value = request.value;
        return {control: states[request.feature]};
    };
    const row = monitorRow(extension.path, {spec, width: 3840, height: 2160, refresh: 60},
        {scale: 2, x: 0, y: 0}, {edid: 'test'}, audio, [spec], command);
    extension._indicator.menu.addMenuItem(row);
    row.menu.open(false);
    await delay(100);
    const items = row.menu._getMenuItems();
    const hardware = items.find(i => i instanceof PopupMenu.PopupMenuSection);
    const rows = hardware._getMenuItems();
    if (rows.length !== 2) throw Error(`Missing hardware sliders: ${items[0].label.text}; calls=${calls.length}`);
    const slider = rows[1].get_children().find(c => c.accessible_name === 'Monitor volume' && 'value' in c);
    slider.value = 0.5;
    slider.value = 0.6;
    await delay(350);
    const writes = calls.filter(c => c[0] === 'set-monitor-control');
    if (writes.length !== 1 || writes[0][1].feature !== 'volume' || writes[0][1].value !== 60)
        throw Error(`Slider writes were not coalesced: ${JSON.stringify(calls)}`);
    const mute = rows[1].get_children().at(-1);
    if (!mute.has_style_pseudo_class('checked')) throw Error('Mute state missing');
    mute.emit('clicked', 1);
    await delay(50);
    if (mute.has_style_pseudo_class('checked') || states.mute.value)
        throw Error('Hardware unmute failed');
    const output = items[2].get_children().find(c => c.accessible_name === 'Current audio output');
    if (!output.has_style_pseudo_class('checked')) throw Error('Output active state missing');
    output.emit('clicked', 1);
    if (selected !== 1) throw Error('Output here did not select the device');
    audio.active = 7;
    for (const listener of audio.listeners) listener();
    if (output.has_style_pseudo_class('checked')) throw Error('Output state did not follow external change');
    const before = calls.length;
    slider.value = 0.8;
    row.destroy();
    await delay(250);
    if (calls.length !== before || audio.listeners.size) throw Error('Destroyed controls retained callbacks');
    // Identical monitor names must never silently select the first audio port.
    const resolve = MonitorAudio.prototype.resolve;
    const routing = {choices: () => [device], saved: () => null};
    if (resolve.call(routing, spec, [spec, [...spec.slice(0, 3), 'other']]))
        throw Error('Ambiguous monitor audio was guessed');
    if (resolve.call(routing, spec, [spec]) !== device)
        throw Error('Unique audio match was not found');
}

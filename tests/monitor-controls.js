import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export async function exerciseControls(extension, delay) {
    const {monitorRow, MonitorAudio, alignMonitorRows} = await import(`file://${extension.path}/monitorControls.js`);
    const tooltips = () => Main.uiGroup.get_children().filter(c =>
        c.has_style_class_name?.('monitor-control-tooltip'));
    const existingTooltips = new Set(tooltips());
    const spec = ['HDMI-1', 'GSM', 'LG HDR 4K', 'test'];
    const device = {get_id: () => 42, get_description: () => 'LG HDR 4K', get_origin: () => 'HDMI 1'};
    let selected = 0;
    let configured = true;
    const audio = {listeners: new Set(), active: 42, saved: () => configured ? 'port' : null, resolve: () => configured ? device : null,
        choices: () => [device], control: {change_output: () => selected++}};
    const calls = [];
    const states = {brightness: {value: 80, maximum: 100}, volume: {value: 40, maximum: 100}, mute: {value: true}};
    const command = async (_path, action, json) => {
        const request = JSON.parse(json);
        calls.push([action, request]);
        if (action !== 'set-monitor-control') throw Error('Panel must not probe hardware');
        states[request.feature].value = request.value;
        return {control: states[request.feature]};
    };
    const capability = {edid: 'test', controls: JSON.parse(JSON.stringify(states)), controls_probed: 1};
    const row = monitorRow(extension.path, {spec, width: 3840, height: 2160, refresh: 60},
        {scale: 2, x: 0, y: 0}, capability, audio, command);
    extension._indicator.menu.addMenuItem(row);
    const other = monitorRow(extension.path, {spec: ['DP-10', 'TEST', 'Other', 'two'], width: 1920, height: 1080, refresh: 59.997},
        {scale: 1, x: 1920, y: 100}, capability, audio, command);
    extension._indicator.menu.addMenuItem(other);
    alignMonitorRows([row, other]);
    const refresh = extension._refresh;
    extension._refresh = () => {};
    extension._indicator.menu.open();
    extension._refresh = refresh;
    row.menu.open(false);
    await delay(100);
    if (calls.length) throw Error('Opening monitor controls probed hardware');
    for (let i = 0; i < row.statColumns.length; i++)
        if (row.statColumns[i].width !== other.statColumns[i].width) throw Error('Statistic columns drifted');
    const items = row.menu._getMenuItems();
    const hardware = items.find(i => i instanceof PopupMenu.PopupMenuSection);
    const rows = hardware._getMenuItems();
    if (rows.length !== 2) throw Error(`Missing hardware sliders: ${items[0].label.text}; calls=${calls.length}`);
    if (rows.some(r => r.has_style_class_name('popup-inactive-menu-item'))) throw Error('Controls use disabled opacity');
    const slider = rows[1].get_children().find(c => c.accessible_name === 'Monitor volume' && 'value' in c);
    const brightness = rows[0].get_children().find(c => c.accessible_name === 'Monitor brightness' && 'value' in c);
    if (brightness.width !== slider.width || brightness.get_transformed_position()[0] !== slider.get_transformed_position()[0])
        throw Error(`Sliders are not aligned: ${brightness.width}, ${slider.width}`);
    if (rows.some(r => r.get_theme_node().get_foreground_color().alpha !== 255)) throw Error('Translucent control foreground');
    slider.value = 0.5;
    slider.value = 0.6;
    await delay(350);
    const writes = calls.filter(c => c[0] === 'set-monitor-control');
    if (writes.length !== 1 || writes[0][1].feature !== 'volume' || writes[0][1].value !== 60)
        throw Error(`Slider writes were not coalesced: ${JSON.stringify(calls)}`);
    const mute = rows[1].get_children().at(-1).child;
    if (!mute.has_style_pseudo_class('checked')) throw Error('Mute state missing');
    mute.grab_key_focus();
    await delay(550);
    if (!tooltips().some(t => t.visible && t.text === 'Unmute Monitor'))
        throw Error('Keyboard focus did not show the current mute action');
    const tooltip = tooltips().find(t => t.visible && t.text === 'Unmute Monitor');
    let menuLayer = mute;
    while (menuLayer.get_parent() !== Main.uiGroup) menuLayer = menuLayer.get_parent();
    const layers = Main.uiGroup.get_children();
    if (layers.indexOf(tooltip) <= layers.indexOf(menuLayer))
        throw Error('Tooltip is stacked behind the open menu');
    mute.emit('clicked', 1);
    await delay(50);
    if (mute.has_style_pseudo_class('checked') || states.mute.value)
        throw Error('Hardware unmute failed');
    await delay(550);
    if (!tooltips().some(t => t.visible && t.text === 'Mute Monitor'))
        throw Error('Mute tooltip did not follow the changed action');
    const output = rows[1].get_children().find(c => c.child?.accessible_name === 'Current Audio Output').child;
    if (!output.has_style_pseudo_class('checked')) throw Error('Output active state missing');
    output.emit('clicked', 1);
    if (selected !== 1) throw Error('Output here did not select the device');
    audio.active = 7;
    for (const listener of audio.listeners) listener();
    if (output.has_style_pseudo_class('checked')) throw Error('Output state did not follow external change');
    configured = false;
    for (const listener of audio.listeners) listener();
    if (output.reactive || output.has_style_class_name('button')) throw Error('Unconfigured volume icon is a button');
    const before = calls.length;
    row.menu.close(false);
    if (tooltips().some(t => t.visible)) throw Error('Closed menu retained a tooltip');
    row.menu.open(false);
    await delay(50);
    if (calls.length !== before || slider.value !== 0.6) throw Error('Reopening lost cached state or probed hardware');
    other.destroy();
    mute.grab_key_focus();
    slider.value = 0.8;
    row.destroy();
    await delay(550);
    if (calls.length !== before || audio.listeners.size) throw Error('Destroyed controls retained callbacks');
    if (tooltips().some(t => !existingTooltips.has(t))) throw Error('Destroyed controls retained tooltips');
    extension._indicator.menu.close();
    const resolve = MonitorAudio.prototype.resolve;
    const routing = {choices: () => [device], saved: () => null, key: () => 'port'};
    if (resolve.call(routing, spec)) throw Error('Unassigned audio output was guessed');
    routing.saved = () => 'port';
    if (resolve.call(routing, spec) !== device) throw Error('Saved output was not restored');
    routing.choices = () => [device, device];
    if (resolve.call(routing, spec)) throw Error('Ambiguous saved output was guessed');
}

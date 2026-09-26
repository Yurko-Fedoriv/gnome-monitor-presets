import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Shell's St buttons don't provide GTK's tooltip-text property. Keep the label
// tied to its button's lifetime, including delayed hover and keyboard focus.
export function buttonTooltip(button) {
    const label = new St.Label({style_class: 'dash-label monitor-control-tooltip',
        reactive: false, visible: false});
    Main.layoutManager.addChrome(label);
    let timer = 0;
    const hide = () => {
        if (timer) GLib.source_remove(timer);
        timer = 0;
        label.hide();
    };
    const eligible = () => button.mapped && button.reactive && !Main.sessionMode.isLocked &&
        (button.hover || button.has_key_focus());
    const show = () => {
        if (!eligible()) return;
        label.text = button.accessible_name;
        label.show();
        // Opening a popup raises it above existing chrome, including this label.
        // Raise the tooltip when shown, after the menu has taken its position.
        label.get_parent().set_child_above_sibling(label, null);
        const [x, y] = button.get_transformed_position();
        const [width, height] = button.get_transformed_size();
        const monitor = Main.layoutManager.findMonitorForActor(button);
        const left = monitor?.x ?? 0;
        const top = monitor?.y ?? 0;
        const right = left + (monitor?.width ?? global.stage.width);
        const bottom = top + (monitor?.height ?? global.stage.height);
        const gap = 6 * St.ThemeContext.get_for_stage(global.stage).scale_factor;
        label.set_position(
            Math.max(left, Math.min(x + (width - label.width) / 2, right - label.width)),
            y - label.height - gap >= top ? y - label.height - gap :
                Math.min(y + height + gap, bottom - label.height));
    };
    const update = () => {
        hide();
        if (!eligible()) return;
        timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            timer = 0;
            show();
            return GLib.SOURCE_REMOVE;
        });
    };
    for (const signal of ['notify::hover', 'notify::mapped', 'notify::reactive',
        'key-focus-in', 'key-focus-out']) button.connect(signal, update);
    button.connect('notify::accessible-name', () => {
        if (label.visible && eligible()) show();
        else update();
    });
    button.connect('clicked', hide);
    button.connect('destroy', () => {
        hide();
        label.destroy();
    });
}

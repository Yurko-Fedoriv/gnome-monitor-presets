import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Pango from 'gi://Pango';

// Open dropdowns show full values, wrapping long names and identifiers.
// Closed rows may ellipsize their selected value to keep preferences compact.
export function fullValueCombo(params = {}) {
    const factory = popup => {
        const result = new Gtk.SignalListItemFactory();
        result.connect('setup', (_factory, item) => {
            const box = new Gtk.Box({spacing: 12});
            box.append(new Gtk.Label({xalign: 0, hexpand: true, wrap: popup,
                wrap_mode: Pango.WrapMode.WORD_CHAR,
                ellipsize: popup ? Pango.EllipsizeMode.NONE : Pango.EllipsizeMode.END,
                max_width_chars: popup ? 64 : 40, margin_top: 6, margin_bottom: 6}));
            if (popup) {
                const check = new Gtk.Image({icon_name: 'object-select-symbolic', pixel_size: 16});
                box.append(check);
                const update = () => { check.opacity = item.selected ? 1 : 0; };
                item.connect('notify::selected', update);
                update();
            }
            item.set_child(box);
        });
        result.connect('bind', (_factory, item) => {
            item.get_child().get_first_child().label = item.get_item().get_string();
        });
        return result;
    };
    return new Adw.ComboRow({...params, title_lines: 0, subtitle_lines: 0,
        factory: factory(false), list_factory: factory(true)});
}

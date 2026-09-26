import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';

// Both selected values and open dropdowns wrap long names and identifiers
// rather than depending on a tooltip to expose the full text.
export function fullValueCombo(params = {}) {
    const factory = popup => {
        const result = new Gtk.SignalListItemFactory();
        result.connect('setup', (_factory, item) => {
            const box = new Gtk.Box({spacing: 12});
            box.append(new Gtk.Label({xalign: 0, hexpand: true, wrap: true,
                wrap_mode: Pango.WrapMode.WORD_CHAR,
                ellipsize: Pango.EllipsizeMode.NONE,
                max_width_chars: popup ? 64 : 40, margin_top: 6, margin_bottom: 6}));
            if (popup) {
                const check = new Gtk.Image({icon_name: 'object-select-symbolic', pixel_size: 16});
                const marker = new Gtk.Box({width_request: 16});
                marker.append(check);
                box.append(marker);
                // Native binding avoids JS notify callbacks during GTK teardown.
                item.bind_property('selected', check, 'visible', GObject.BindingFlags.SYNC_CREATE);
            }
            item.set_child(box);
        });
        result.connect('bind', (_factory, item) => {
            item.get_child().get_first_child().label = item.get_item().get_string();
        });
        return result;
    };
    const row = new Adw.ComboRow({...params, title_lines: 0, subtitle_lines: 0,
        factory: factory(false), list_factory: factory(true)});
    // The popover belongs to the arrow at the right edge of the row. Align its
    // right edge there so long choices use the space to the left of the arrow.
    const alignPopover = widget => {
        if (widget instanceof Gtk.Popover) {
            widget.halign = Gtk.Align.END;
            return;
        }
        for (let child = widget.get_first_child(); child; child = child.get_next_sibling())
            alignPopover(child);
    };
    alignPopover(row);
    return row;
}

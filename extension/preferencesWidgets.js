import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import {monitorName} from './monitorNames.js';

export function alignedDisplaySummaries(layouts) {
    const summaries = layouts.map(layout => layout.logical.flatMap(group => group.monitors.map(monitor => [
        `${monitorName(monitor.spec)}${group.primary ? '*' : ''}`,
        `${monitor.width}×${monitor.height}`,
        `${Number(monitor.refresh.toFixed(2))} Hz`,
        `${Math.round(group.scale * 100)}%`,
        `X: ${group.x}`, `Y: ${group.y}`,
    ])));
    const rows = summaries.flat();
    if (!rows.length) return layouts.map(() => '');
    const widths = rows[0].map((_, column) => Math.max(...rows.map(row => row[column].length)));
    return summaries.map(summary => {
        if (!summary.length) return '';
        const text = summary.map(row => row.map((value, column) =>
            column === row.length - 1 ? value : value.padEnd(widths[column])).join('  ')).join('\n');
        // Share widths across all presets, using a fixed-width font so padding
        // aligns reliably. Escape monitor identifiers before applying markup.
        return `<span font_family="monospace">${GLib.markup_escape_text(text, -1)}</span>`;
    });
}

// Closed selectors stay on one line; the open list always shows full values.
export function fullValueCombo(params = {}, {selectedText = text => text} = {}) {
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
                const marker = new Gtk.Box({width_request: 16});
                marker.append(check);
                box.append(marker);
                // Native binding avoids JS notify callbacks during GTK teardown.
                item.bind_property('selected', check, 'visible', GObject.BindingFlags.SYNC_CREATE);
            }
            item.set_child(box);
        });
        result.connect('bind', (_factory, item) => {
            const text = item.get_item().get_string();
            item.get_child().get_first_child().label = popup ? text : selectedText(text);
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

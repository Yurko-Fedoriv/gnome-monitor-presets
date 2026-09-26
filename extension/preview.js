import Clutter from 'gi://Clutter';
import St from 'gi://St';

export function details(layout) {
    const grid = new Clutter.GridLayout();
    const box = new St.Widget({layout_manager: grid, x_expand: true});
    let row = 0;
    for (const group of layout.logical) {
        for (const m of group.monitors) {
            const values = [`${m.spec[0]}${group.primary ? '*' : ''}`, `${m.width}×${m.height}`,
                `${Number(m.refresh.toFixed(2))} Hz`, `${Math.round(group.scale * 100)}%`,
                `X: ${group.x}`, `Y: ${group.y}`];
            values.forEach((text, column) => grid.attach(new St.Label({text,
                style: 'padding: 3px 10px;', x_align: Clutter.ActorAlign.START}), column, row, 1, 1));
            row++;
        }
    }
    return box;
}

export function preview(layout, width = 150, height = 80) {
    const area = new St.DrawingArea({width, height, x_align: Clutter.ActorAlign.CENTER});
    area.connect('repaint', () => {
        const cr = area.get_context();
        const [w, h] = area.get_surface_size();
        const rects = layout.logical.flatMap(group => group.monitors.map((m, index) => {
            const divisor = layout.layout_mode === 1 ? group.scale : 1;
            const rotated = group.transform % 2 === 1;
            return {x: group.x, y: group.y,
                w: (rotated ? m.height : m.width) / divisor,
                h: (rotated ? m.width : m.height) / divisor,
                primary: group.primary, index};
        }));
        if (rects.length) {
            const minX = Math.min(...rects.map(r => r.x));
            const minY = Math.min(...rects.map(r => r.y));
            const maxX = Math.max(...rects.map(r => r.x + r.w));
            const maxY = Math.max(...rects.map(r => r.y + r.h));
            const factor = Math.min((w - 20) / (maxX - minX), (h - 20) / (maxY - minY));
            const offsetX = (w - (maxX - minX) * factor) / 2;
            const offsetY = (h - (maxY - minY) * factor) / 2;
            const color = area.get_theme_node().get_foreground_color();
            for (const r of rects) {
                const x = offsetX + (r.x - minX) * factor + r.index * 4;
                const y = offsetY + (r.y - minY) * factor + r.index * 4;
                const rw = Math.max(5, r.w * factor - 4);
                const rh = Math.max(5, r.h * factor - 4);
                cr.setSourceRGBA(color.red / 255, color.green / 255, color.blue / 255, 0.15);
                cr.rectangle(x, y, rw, rh);
                cr.fillPreserve();
                cr.setSourceRGBA(color.red / 255, color.green / 255, color.blue / 255, 1);
                cr.setLineWidth(r.primary ? 2.5 : 1);
                cr.stroke();
                cr.moveTo(x + rw * 0.35, y + rh + 3);
                cr.lineTo(x + rw * 0.65, y + rh + 3);
                cr.stroke();
            }
        }
        cr.$dispose();
    });
    return area;
}

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

function read(path) {
    return new TextDecoder().decode(Gio.File.new_for_path(path).load_contents(null)[1]).trim();
}

export function usbKey(device) {
    return `${device.vendor}:${device.product}:${device.serial || device.path}`;
}

export function usbDevices(root = '/sys/bus/usb/devices') {
    const directory = Gio.File.new_for_path(root);
    const children = directory.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
    const devices = [];
    const optional = path => { try { return read(path); } catch (_) { return ''; } };
    try {
        let child;
        while ((child = children.next_file(null))) {
            const name = child.get_name();
            const path = `${root}/${name}`;
            try {
                const vendor = read(`${path}/idVendor`);
                const product = read(`${path}/idProduct`);
                const serial = optional(`${path}/serial`);
                const hub = optional(`${path}/bDeviceClass`) === '09';
                const label = [optional(`${path}/manufacturer`), optional(`${path}/product`)].filter(Boolean).join(' ');
                devices.push({vendor, product, serial, path: serial ? '' : name, hub,
                    name: `${hub ? 'USB hub · ' : ''}${label || `${vendor}:${product}`} (${name})`});
            } catch (_) { /* USB interface or device disappeared. */ }
        }
    } finally {
        children.close(null);
    }
    return devices.sort((a, b) => Number(b.hub) - Number(a.hub) || a.name.localeCompare(b.name));
}

export function usbPresent(identity, root = '/sys/bus/usb/devices') {
    return usbDevices(root).some(d => d.vendor === identity.vendor && d.product === identity.product &&
        (!identity.serial || d.serial === identity.serial) && (!identity.path || d.path === identity.path));
}

// Baseline only at startup; require two seconds of stable state per edge.
export class StableSwitch {
    sample(present, now) {
        if (this.current === undefined) {
            this.current = this.candidate = present;
            this.since = now;
        }
        if (present !== this.candidate) {
            this.candidate = present;
            this.since = now;
        }
        if (this.current !== present && now - this.since >= 2) {
            this.current = present;
            return present ? 'here' : 'away';
        }
        return null;
    }
}

export function consumeActionDisconnect(settings, now = Date.now() / 1000) {
    if (settings.get_double('action-suppress-kvm-until') <= now) return false;
    settings.set_double('action-suppress-kvm-until', 0);
    return true;
}

export class KvmWatcher {
    constructor(settings, command) {
        this.settings = settings;
        this.command = command;
        this.signals = ['kvm-disconnect-enabled', 'kvm-config', 'kvm-detect-until'].map(key =>
            settings.connect(`changed::${key}`, () => this.restart()));
        try {
            this.sleepSignal = Gio.DBus.system.signal_subscribe('org.freedesktop.login1',
                'org.freedesktop.login1.Manager', 'PrepareForSleep', '/org/freedesktop/login1',
                null, Gio.DBusSignalFlags.NONE, (_connection, _sender, _path, _interface, _signal, params) => {
                    this.sleeping = params.deep_unpack()[0];
                    this.pending = null;
                    if (!this.sleeping && this.edge)
                        this.edge = new StableSwitch();
                });
        } catch (error) {
            console.error(`Monitor Presets KVM: ${error.message}`);
        }
        this.restart();
    }

    restart() {
        if (this.timer)
            GLib.source_remove(this.timer);
        this.timer = 0;
        this.pending = null;
        if (!this.settings.get_boolean('kvm-disconnect-enabled'))
            return;
        try {
            this.config = JSON.parse(this.settings.get_string('kvm-config'));
            if (!this.config.usb)
                return;
            this.edge = new StableSwitch();
            this.tick();
            this.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
                this.tick();
                return GLib.SOURCE_CONTINUE;
            });
        } catch (error) {
            console.error(`Monitor Presets KVM: ${error.message}`);
        }
    }

    tick() {
        if (this.sleeping || this.settings.get_double('kvm-detect-until') > Date.now() / 1000) {
            this.edge = new StableSwitch();
            this.pending = null;
            return;
        }
        try {
            const action = this.edge.sample(usbPresent(this.config.usb), GLib.get_monotonic_time() / 1e6);
            if (action === 'away') {
                if (consumeActionDisconnect(this.settings)) {
                    this.pending = null;
                } else this.pending = true;
            }
            if (usbPresent(this.config.usb))
                this.pending = null;
            if (this.pending && !this.busy) {
                this.pending = null;
                this.busy = true;
                this.command('kvm-disconnect').finally(() => { this.busy = false; });
            }
        } catch (error) {
            console.error(`Monitor Presets KVM: ${error.message}`);
        }
    }

    destroy() {
        if (this.timer)
            GLib.source_remove(this.timer);
        this.timer = 0;
        this.pending = null;
        if (this.sleepSignal)
            Gio.DBus.system.signal_unsubscribe(this.sleepSignal);
        this.sleepSignal = 0;
        for (const signal of this.signals)
            this.settings.disconnect(signal);
    }
}

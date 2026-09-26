import {StableSwitch, usbDevices, usbKey, consumeActionDisconnect} from '../extension/kvm.js';

function equal(actual, expected) {
    if (actual !== expected) throw new Error(`${actual} !== ${expected}`);
}
const edge = new StableSwitch();
equal(edge.sample(false, 0), null); // No startup disconnect.
equal(edge.sample(true, 1), null);
equal(edge.sample(true, 3), 'here');
equal(edge.sample(false, 4), null);
equal(edge.sample(true, 5), null); // A brief USB disturbance is ignored.
equal(edge.sample(false, 6), null);
equal(edge.sample(false, 8), 'away');
equal(edge.sample(false, 20), null); // One action per edge.
const devices = usbDevices();
for (const device of devices) {
    if (!device.name || !usbKey(device)) throw new Error('USB device lacks identity');
}
print('PASS: KVM debounce, startup baseline and USB enumeration');

let deadline = 30;
const settings = {get_double: () => deadline, set_double: (_key, value) => { deadline = value; }};
const guarded = new StableSwitch();
guarded.sample(true, 0);
guarded.sample(false, 1);
equal(guarded.sample(false, 3), 'away');
equal(consumeActionDisconnect(settings, 3), true);
guarded.sample(true, 4);
equal(guarded.sample(true, 6), 'here');
guarded.sample(false, 7);
equal(guarded.sample(false, 9), 'away');
equal(consumeActionDisconnect(settings, 9), false); // Next real disconnect works even within old deadline.
deadline = 5;
equal(consumeActionDisconnect(settings, 6), false); // No event cannot leave a permanent suppression.
print('PASS: one-shot action disconnect suppression and expiration');

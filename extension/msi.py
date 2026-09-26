"""MSI monitor HID queries. Protocol reference: couriersud/msigd (00110/00500)."""
import os
from pathlib import Path
import select
import time
import json
import sys


def devices():
    result = []
    for path in Path('/sys/class/hidraw').glob('*'):
        try:
            info = dict(line.split('=', 1) for line in (path / 'device/uevent').read_text().splitlines() if '=' in line)
            if info.get('HID_ID') != '0003:00001462:00003FA4':
                continue
            node = '/dev/' + path.name
            result.append({'vendor': '1462', 'product': '3fa4', 'serial': info.get('HID_UNIQ', ''),
                           'name': info.get('HID_NAME', 'MSI monitor'), 'node': node,
                           'accessible': os.access(node, os.R_OK | os.W_OK)})
        except OSError:
            pass
    return result


def open_device(identity):
    found = [d for d in devices() if d['serial'] == identity.get('serial')]
    if len(found) != 1:
        raise ValueError('MSI controller is disconnected or ambiguous')
    return os.open(found[0]['node'], os.O_RDWR | os.O_NONBLOCK)


def exchange(fd, command, prefix):
    import fcntl
    root = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'monitor-presets'
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'msi-usb.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        while select.select([fd], [], [], 0)[0]:
            if not os.read(fd, 64):
                raise OSError('MSI disconnected')
        os.write(fd, (b'\x01' + command + b'\r').ljust(64, b'\x00'))
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            if not select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
                break
            response = os.read(fd, 64).split(b'\r')[0]
            if response.startswith(prefix):
                return response[len(prefix):]
        raise TimeoutError('MSI query timed out')


def query(fd, setting):
    if setting not in ('00110', '00500', '008>0'):
        raise ValueError('Unsupported MSI query')
    return int(exchange(fd, b'58' + setting.encode(), b'\x015b' + setting.encode()).decode())


def switch_input(identity, code):
    value = {17: 0, 18: 1, 15: 2, 16: 3}[code]
    fd = open_device(identity)
    try:
        if query(fd, '00500') == value:
            return
        # Switching away can disconnect the controller before its acknowledgement.
        try:
            exchange(fd, b'5b00500' + f'{value:03}'.encode(), b'\x015600+')
        except (TimeoutError, OSError):
            if any(d['serial'] == identity.get('serial') for d in devices()):
                raise
    finally:
        os.close(fd)


def watch(identity):
    # Reopen after KVM reconnect. Baseline every reconnect avoids phantom presses.
    parent = os.getppid()
    while os.getppid() == parent:
        try:
            fd = open_device(identity)
            try:
                previous = query(fd, '00110')
                while os.getppid() == parent:
                    time.sleep(0.25)
                    current = query(fd, '00110')
                    if current == 1 and previous == 0:
                        print(json.dumps({'pressed': True}), flush=True)
                    previous = current
            finally:
                os.close(fd)
        except (OSError, ValueError):
            time.sleep(2)


if __name__ == '__main__':
    watch(json.loads(sys.argv[1]))

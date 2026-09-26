"""Tested LG HDR 4K F4 transport. Never fall back to standard VCP 60 writes."""
import subprocess
from .generic_ddc import GenericDDC


class LGHDR(GenericDDC):
    id = 'lg-hdr-4k'
    transport = 'lg-f4'
    default_transport = 'blocked'  # Legacy requests must have an explicit tested profile.
    readback = 'unreliable'
    values = {15: 0xd0, 16: 0xd1, 17: 0x90, 18: 0x91}
    manual_options = ({'key': 'usb_c', 'type': 'boolean', 'label': 'Has Type-C',
        'default': False, 'tooltip': 'LG reports the same input list with or without USB-C.\n'
        'Enable this only for the model with a USB-C video port.'},)

    def matches(self, spec):
        return spec[1:3] == ['GSM', 'LG HDR 4K']

    def choices(self, entry):
        codes = [code for code in entry.get('codes', [15, 16, 17, 18]) if code in (15, 17, 18)]
        if entry.get('usb_c'):
            codes = sorted(set(codes + [16]))
        labels = {15: 'DisplayPort', 16: 'USB-C', 17: 'HDMI 1', 18: 'HDMI 2'}
        return [{'code': code, 'label': labels[code]} for code in codes]

    def profile(self, code):
        if code not in self.values:
            raise ValueError('DP 2 is not configured for this LG model')
        return {'transport': self.transport, 'values': {str(code): self.values[code]}}

    def allows_transport(self, transport):
        # Preserve legacy MSI override acceptance but never allow standard DDC.
        return transport in ('lg-f4', 'msi-usb')

    def switch(self, code, bus, profile, report, read):
        value = profile.get('values', {}).get(str(code))
        if type(value) is not int or not 1 <= value <= 255:
            raise ValueError('No tested LG input command configured for this input')
        report.update(feature='f4', value=value, readback_reliable=False)
        proc = subprocess.run(['ddcutil', '--bus', str(bus), '--noverify', '--mccs', '2.2',
                               '--i2c-source-addr=0x50', '--maxtries', '1,.,.',
                               'setvcp', 'f4', f'0x{value:02x}'],
                              capture_output=True, text=True, timeout=8)
        if proc.returncode:
            raise ValueError(proc.stderr.strip() or proc.stdout.strip() or 'LG input request failed')
        report['status'] = 'request-sent'

"""MSI MAG323UPF USB profile; HID wire protocol remains in the reusable msi helper."""
import os
import msi
from .generic_ddc import GenericDDC


class MSIMAG(GenericDDC):
    id = 'msi-mag323upf'
    transport = 'msi-usb'
    channel = 'usb-hid'
    readback = 'usb-current-input'
    setup = 'Run hardware/enable-msi-access.sh to grant the active user MSI HID access.'

    def matches(self, spec):
        return spec[2] == 'MSI MAG323UPF'

    def choices(self, entry):
        return [{'code': code, 'label': label} for code, label in
                [(15, 'DisplayPort'), (16, 'USB-C'), (17, 'HDMI 1'), (18, 'HDMI 2')]]

    def controller(self):
        controls = msi.devices()
        if len(controls) != 1:
            raise ValueError('MSI controller unavailable or ambiguous')
        return controls[0]

    def discover(self, target, displays):
        fd = msi.open_device(self.controller())
        try:
            if msi.query(fd, '00500') not in (0, 1, 2, 3):
                raise ValueError('Unknown MSI input profile')
        finally:
            os.close(fd)
        return {'codes': [15, 16, 17, 18], 'source': 'MSI MAG323UPF USB profile'}

    def profile(self, code):
        return {'transport': self.transport, 'usb': self.controller()}

    def switch(self, code, bus, profile, report, read):
        msi.switch_input(profile['usb'], code)
        report['status'] = 'request-sent'

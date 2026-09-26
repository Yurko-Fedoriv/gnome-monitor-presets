"""Fallback MCCS input discovery and switching; no vendor-specific assumptions."""
import os
import re
import subprocess

LABELS = {1: 'VGA 1', 2: 'VGA 2', 3: 'DVI 1', 4: 'DVI 2',
          15: 'DisplayPort 1', 16: 'DisplayPort 2', 17: 'HDMI 1', 18: 'HDMI 2', 27: 'USB-C'}


def parse_capabilities(output):
    section = re.search(r'^\s*Feature: 60\b(.*?)(?=^\s*Feature:|\Z)', output,
                        re.MULTILINE | re.DOTALL)
    if not section:
        raise ValueError('Monitor did not advertise input selection')
    codes = sorted({int(v, 16) for v in re.findall(r'^\s*([0-9a-fA-F]{2}):', section[1], re.MULTILINE)})
    if not codes:
        raise ValueError('Monitor did not advertise input values')
    return codes


def read_input(bus):
    proc = subprocess.run(['ddcutil', '--bus', str(bus), '--brief', 'getvcp', '60'],
                          capture_output=True, text=True, timeout=8,
                          env={**os.environ, 'LC_ALL': 'C'})
    match = re.search(r'^VCP 60 SNC x([0-9a-fA-F]{1,4})\s*$', proc.stdout, re.MULTILINE)
    if proc.returncode or not match:
        raise ValueError(proc.stderr.strip() or proc.stdout.strip() or 'No input response')
    code = int(match[1], 16)
    if not 1 <= code <= 255:
        raise ValueError('Unsupported input code')
    return code


class GenericDDC:
    id = 'generic-ddc'
    transport = 'standard'
    channel = 'ddc'
    readback = 'standard-vcp60'
    default_transport = 'standard'
    manual_options = ()
    setup = 'Install ddcutil and grant your user access to the monitor I2C devices.'

    def matches(self, spec):
        return True

    def choices(self, entry):
        return [{'code': code, 'label': LABELS.get(code, f'Input 0x{code:02X}')}
                for code in entry.get('codes', [15, 16, 17, 18])]

    def discover(self, target, displays):
        matches = [d for d in displays if d['connector'] == target['connector']
                   and d['edid'] == target['edid'] and d.get('bus') is not None]
        if len(matches) != 1:
            raise ValueError('Monitor is disconnected or has no DDC bus')
        proc = subprocess.run(['ddcutil', '--bus', str(matches[0]['bus']), '--mccs', '2.2',
                               '--disable-capabilities-cache', 'capabilities'],
                              capture_output=True, text=True, timeout=20,
                              env={**os.environ, 'LC_ALL': 'C'})
        if proc.returncode:
            raise ValueError(proc.stderr.strip() or proc.stdout.strip() or 'DDC query failed')
        return {'codes': parse_capabilities(proc.stdout), 'raw': proc.stdout}

    def check_target(self, target, current):
        # Deliberately preserve the existing action policy for every driver.
        # Enabled/EDID-visible means eligible to try, not proof of DDC reachability.
        if not any(m['spec'] == target['spec'] for group in current.get('logical', [])
                   for m in group['monitors']):
            raise ValueError(f"{target['connector']}: monitor is disabled; skipping input redirect")

    def profile(self, code):
        return {}

    def allows_transport(self, transport):
        return True

    def switch(self, code, bus, profile, report, read):
        try:
            report['before'] = read(bus)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            # Some monitors accept writes even when input reads are unsupported.
            report['read_error'] = str(error)
        report['readback_reliable'] = True
        if report.get('before') == code:
            report['status'] = 'already-selected'
            return
        proc = subprocess.run(['ddcutil', '--bus', str(bus), '--noverify', 'setvcp', '60', f'0x{code:02x}'],
                              capture_output=True, text=True, timeout=8)
        if proc.returncode:
            raise ValueError(proc.stderr.strip() or proc.stdout.strip() or 'Input request failed')
        report['status'] = 'request-sent'
        try:
            report['after'] = read(bus)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            report['verification_error'] = str(error)
        else:
            if report['after'] != code:
                raise ValueError(f"Monitor still reports input 0x{report['after']:02x} after requesting 0x{code:02x}")
            report['status'] = 'confirmed'

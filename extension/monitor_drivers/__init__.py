"""Explicit built-in driver registry. Imports never access hardware.

Add a reviewed driver here; no arbitrary discovery of executable plugins from
user-writable configuration directories. Cache and action values remain stable.
"""
from .generic_ddc import GenericDDC
from .lg_hdr import LGHDR
from .msi_mag import MSIMAG

GENERIC = GenericDDC()
DRIVERS = (LGHDR(), MSIMAG())
TRANSPORTS = {driver.transport: driver for driver in (*DRIVERS, GENERIC)}


def select(spec):
    matches = [driver for driver in DRIVERS if driver.matches(spec)]
    if len(matches) > 1:
        raise ValueError('Ambiguous monitor driver match')
    return matches[0] if matches else GENERIC


def transport(name):
    if name == 'blocked':
        raise ValueError('Input switching paused: standard DDC causes LG lockups; '
                         'an alternative input command must be tested first.')
    if name not in TRANSPORTS:
        raise ValueError('Unsupported input transport for this monitor')
    return TRANSPORTS[name]


def options(spec, entry):
    return [{**option, 'value': entry.get(option['key'], option['default'])}
            for option in select(spec).manual_options]


def update_options(spec, entry, changes):
    declared = {option['key']: option for option in select(spec).manual_options}
    if not changes or any(key not in declared for key in changes):
        raise ValueError('Invalid monitor profile')
    for key, value in changes.items():
        if declared[key]['type'] != 'boolean' or type(value) is not bool:
            raise ValueError('Invalid monitor profile')
    return {**entry, **changes}

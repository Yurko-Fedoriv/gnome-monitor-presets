#!/bin/sh
set -eu
cd "$(dirname "$0")"
sudo install -m 644 70-monitor-presets-msi.rules /etc/udev/rules.d/70-monitor-presets-msi.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=add
sudo udevadm settle

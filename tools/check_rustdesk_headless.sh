#!/usr/bin/env bash
set -u

echo "=== RustDesk ==="
rustdesk --version 2>&1
systemctl is-enabled rustdesk 2>&1
systemctl is-active rustdesk 2>&1

echo "=== X11/GDM ==="
grep -E '^[[:space:]]*WaylandEnable=' /etc/gdm3/custom.conf 2>/dev/null || true
loginctl list-sessions --no-legend 2>/dev/null || true
pgrep -a Xorg 2>/dev/null || true
ls -la /tmp/.X11-unix 2>/dev/null || true

echo "=== Driver y configuración virtual ==="
ls -l /usr/lib/xorg/modules/drivers/dummy_drv.so 2>&1
ls -l /etc/rustdesk/xorg.conf /etc/rustdesk/startwm.sh 2>&1

echo "=== Logs recientes ==="
journalctl -u rustdesk -b --no-pager -n 80 2>&1

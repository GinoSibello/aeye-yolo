#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Ejecutá con sudo: sudo bash tools/restore_jetson_nvidia_display.sh" >&2
  exit 1
fi

backup=/etc/X11/xorg.conf.aeye-nvidia-backup
target=/etc/X11/xorg.conf

[[ -f "$backup" ]] || { echo "No existe el backup NVIDIA: $backup" >&2; exit 1; }
grep -q 'Driver[[:space:]]*"nvidia"' "$backup" || {
  echo "El backup no parece ser una configuración NVIDIA; no se restaura." >&2
  exit 1
}

cp -a "$backup" "$target"
echo "Configuración NVIDIA restaurada en $target"
echo "Reiniciá con: sudo reboot"

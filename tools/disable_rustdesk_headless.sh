#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Ejecutá este script con sudo: sudo bash tools/disable_rustdesk_headless.sh" >&2
  exit 1
fi

rustdesk --option allow-linux-headless N
systemctl restart rustdesk
echo "Modo headless de RustDesk deshabilitado. No se modificó /etc/X11/xorg.conf."

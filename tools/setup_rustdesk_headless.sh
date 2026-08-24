#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Ejecutá este script con sudo: sudo bash tools/setup_rustdesk_headless.sh" >&2
  exit 1
fi

echo "[1/6] Verificando RustDesk y GNOME/X11..."
command -v rustdesk >/dev/null || { echo "RustDesk no está instalado" >&2; exit 1; }
command -v Xorg >/dev/null || { echo "Xorg no está instalado" >&2; exit 1; }

if [[ -f /etc/gdm3/custom.conf ]] && ! grep -Eq '^[[:space:]]*WaylandEnable=false' /etc/gdm3/custom.conf; then
  echo "GDM no está forzado a X11. No se modifica automáticamente." >&2
  echo "Configurá WaylandEnable=false en /etc/gdm3/custom.conf y volvé a ejecutar." >&2
  exit 1
fi

echo "[2/6] Preservando la configuración NVIDIA de la Jetson..."
if [[ -f /etc/X11/xorg.conf ]]; then
  backup="/etc/X11/xorg.conf.aeye-backup-$(date +%Y%m%d-%H%M%S)"
  cp -a /etc/X11/xorg.conf "$backup"
  echo "Backup: $backup"
fi

echo "[3/6] Instalando el driver virtual de Xorg..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y xserver-xorg-video-dummy

dummy_driver=/usr/lib/xorg/modules/drivers/dummy_drv.so
[[ -f "$dummy_driver" ]] || {
  echo "La instalación terminó pero no existe $dummy_driver" >&2
  exit 1
}

echo "[4/6] Verificando los recursos headless de RustDesk..."
[[ -f /etc/rustdesk/xorg.conf ]] || {
  echo "Falta /etc/rustdesk/xorg.conf; reinstalá el paquete nativo .deb de RustDesk" >&2
  exit 1
}
[[ -x /etc/rustdesk/startwm.sh ]] || chmod +x /etc/rustdesk/startwm.sh

echo "[5/6] Habilitando headless para el servicio administrativo..."
rustdesk --option allow-linux-headless Y
systemctl enable rustdesk
systemctl restart rustdesk

echo "[6/6] Estado final..."
echo "RustDesk: $(rustdesk --version)"
echo "Servicio: $(systemctl is-active rustdesk)"
echo "Driver dummy: $dummy_driver"
echo "ID RustDesk:"
rustdesk --get-id || true

echo
echo "Configuración lista. Mantené SSH abierto y reiniciá con: sudo reboot"
echo "Después del reinicio, probá RustDesk sin HDMI conectado."

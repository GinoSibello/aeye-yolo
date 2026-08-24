#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Ejecutá con sudo: sudo bash tools/setup_jetson_dummy_display.sh" >&2
  exit 1
fi

nvidia_config=/etc/X11/xorg.conf
backup=/etc/X11/xorg.conf.aeye-nvidia-backup
dummy_source=/etc/rustdesk/xorg.conf
test_log=/tmp/aeye-xorg-dummy-test.log

echo "[1/5] Verificando archivos y driver..."
[[ -f "$dummy_source" ]] || { echo "Falta $dummy_source" >&2; exit 1; }
[[ -f /usr/lib/xorg/modules/drivers/dummy_drv.so ]] || {
  echo "Falta xserver-xorg-video-dummy. Ejecutá primero setup_rustdesk_headless.sh" >&2
  exit 1
}

echo "[2/5] Guardando la configuración NVIDIA original..."
if [[ ! -f "$backup" ]]; then
  if [[ ! -f "$nvidia_config" ]] || ! grep -q 'Driver[[:space:]]*"nvidia"' "$nvidia_config"; then
    echo "No encontré una configuración NVIDIA válida en $nvidia_config; no continúo." >&2
    exit 1
  fi
  cp -a "$nvidia_config" "$backup"
  echo "Backup permanente: $backup"
else
  echo "El backup permanente ya existe y no será sobrescrito: $backup"
fi

echo "[3/5] Probando un Xorg dummy aislado en :99..."
rm -f /tmp/.X99-lock "$test_log"
Xorg :99 -config "$dummy_source" -noreset -nolisten tcp -novtswitch -sharevts \
  -logfile "$test_log" >/dev/null 2>&1 &
test_pid=$!
sleep 3
if ! kill -0 "$test_pid" 2>/dev/null; then
  wait "$test_pid" || true
  echo "El Xorg dummy de prueba no arrancó. Log:" >&2
  tail -80 "$test_log" >&2 || true
  exit 1
fi
kill "$test_pid"
wait "$test_pid" 2>/dev/null || true
echo "Prueba Xorg dummy: OK"

echo "[4/5] Instalando el display virtual 1920x1080..."
install -o root -g root -m 0644 "$dummy_source" "$nvidia_config"

echo "[5/5] Comprobando RustDesk..."
rustdesk --option allow-linux-headless Y
systemctl enable rustdesk

echo
echo "Configuración instalada, pero GDM todavía no fue reiniciado."
echo "Mantené SSH disponible y ejecutá: sudo reboot"
echo "Restauración por SSH: sudo bash tools/restore_jetson_nvidia_display.sh"

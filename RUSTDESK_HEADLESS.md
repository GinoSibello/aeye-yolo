# RustDesk headless en Jetson AEYE

Estado detectado antes de configurar:

- Ubuntu 24.04 con GNOME/GDM.
- Sesión gráfica X11 y `WaylandEnable=false`.
- RustDesk 1.4.9 instalado, habilitado y activo.
- `/etc/X11/xorg.conf` pertenece a NVIDIA Tegra y no debe reemplazarse.
- RustDesk ya proporciona `/etc/rustdesk/xorg.conf` (1920x1080/1280x720).
- Falta el paquete `xserver-xorg-video-dummy`.

## Preparación

Antes de reiniciar, confirmar que SSH funciona desde otra computadora. Mantener
esa sesión abierta durante la primera prueba.

## Instalación

```bash
cd ~/aeye-yolo
sudo bash tools/setup_rustdesk_headless.sh
```

El script instala el driver dummy, habilita `allow-linux-headless` para el
servicio root de RustDesk y reinicia el servicio. No sustituye la configuración
Xorg de NVIDIA ni cambia GDM por LightDM.

Después:

```bash
sudo reboot
```

Desconectar HDMI y probar RustDesk. Para diagnosticar desde SSH:

```bash
cd ~/aeye-yolo
bash tools/check_rustdesk_headless.sh
```

Para deshabilitar solamente el modo headless:

```bash
sudo bash tools/disable_rustdesk_headless.sh
```

No se desinstala el driver dummy automáticamente: dejarlo instalado no obliga a
Xorg a usarlo y evita una operación destructiva innecesaria.

## Jetson: Xorg existe pero RustDesk informa “no display”

En Tegra, `AllowEmptyInitialConfiguration` puede iniciar Xorg sin crear un
framebuffer cuando no hay HDMI/DisplayPort. RustDesk ve el servidor Xorg pero no
encuentra un monitor capturable. Para usar un escritorio exclusivamente virtual:

```bash
cd ~/aeye-yolo
sudo bash tools/setup_jetson_dummy_display.sh
sudo reboot
```

El instalador conserva la configuración NVIDIA en
`/etc/X11/xorg.conf.aeye-nvidia-backup`, prueba el driver dummy en `:99` y luego
configura 1920x1080. No reinicia GDM por sí solo.

Para volver a usar la salida física NVIDIA:

```bash
cd ~/aeye-yolo
sudo bash tools/restore_jetson_nvidia_display.sh
sudo reboot
```

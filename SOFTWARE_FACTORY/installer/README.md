# Instalador Kaanbal

El asistente web se ejecuta como un servicio systemd privilegiado temporal en
Ubuntu Server. El acceso recomendado desde otra PC es por túnel SSH hacia
loopback; no publiques el puerto HTTP ni compartas su token de sesión.

Sigue el [guía de instalación](../../docs/guides/INSTALL_UBUNTU.md)
para preparar Ubuntu, configurar la clave pública SSH y el alias, descargar una
revisión pública y completar la UI. La instalación integral sobre Ubuntu 26.04,
el reinicio y la recuperación deben verificarse antes de declararla lista.

## Inicio desde un checkout existente

Desde `SOFTWARE_FACTORY`:

```bash
sudo bash ./install.sh --lan
```

El modo LAN imprime una URL como
`http://192.168.1.50:3000/?token=...`, lista para copiar al navegador desde una
PC de la misma red. El token controla el instalador mientras está activo: no
compartas la URL ni la abras desde una red que no sea de confianza.

Para mantener los puertos únicamente en el servidor usa:

```bash
sudo bash ./install.sh --ssh-tunnel
```

Sudo solicita la contraseña de Ubuntu al humano si corresponde. No se requiere
NOPASSWD. El servicio continúa aunque se cierre la sesión SSH.

En modo `--ssh-tunnel`, desde otra terminal de tu PC:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:3000:127.0.0.1:3000 -L 127.0.0.1:4600:127.0.0.1:4600 -L 127.0.0.1:8080:127.0.0.1:8080 laboratorio-lab
```

Sustituye el alias y abre `http://localhost:3000/?token=...` con el token impreso.
El puerto 4600 sirve al asistente IA y 8080 al acceso provisional de Argo. Los
puertos ocupados se reportan; el script no mata los procesos ajenos que los usan.

## Archivo de configuración opcional

```bash
sudo bash ./install.sh --env /ruta/segura/configuracion
sudo bash ./install.sh --check --env /ruta/segura/configuracion
sudo bash ./install.sh --unattended --env /ruta/segura/configuracion
```

Estos modos conservan el formato de variables de `config.example`. Las
credenciales existentes no se reemplazan por otro archivo: reanuda sin `--env`
o administra el archivo persistente explícitamente. Los agentes no deben leer
archivos `.env`, claves privadas ni mostrar secretos. `--check` valida los
proveedores sin desplegar; preparar dependencias/configuración local puede
crear archivos. No equivale a un dry-run del sistema completo.

Credenciales: `/etc/kaanbal/installer.env`, root-only. Estado:
`/var/lib/kaanbal-installer/state.json`. El token temporal se revoca al finalizar
el asistente. Verifica login y funcionamiento antes de cerrar.

GitHub requiere permisos para crear/escribir repos y workflows (PAT classic:
`repo`, `workflow`, y los permisos de organización necesarios). Docker Hub sigue
siendo parte del flujo actual. Cloudflare/dominio y Tailscale dependen del canal
elegido. La validación OAuth no sustituye la comprobación de conectividad VPN.

## Reinicio y recuperación

Vault requiere claves originales para desbloquearse después de reiniciar;
este piloto no promete auto-unseal. Conserva un respaldo protegido fuera del
servidor, además del backup de datos, y prueba la recuperación. No introduzcas
claves en argumentos de shell o mensajes. El manual incluye las verificaciones
que deben registrarse con evidencia sin secretos.

## Reset de laboratorio

Los resets son destructivos y no forman parte de la instalación normal. Lee
`sudo bash ./install.sh --help` y revisa los recursos afectados antes de usarlos.
`--reset-remote` puede borrar repos e imágenes del sistema. Nunca se necesita
para reabrir el asistente ni para descargar la versión pública por primera vez.

El ejemplo versionado para modo desatendido es `installer/config.example`; cópialo fuera del checkout y protege el archivo rellenado con permisos 600.

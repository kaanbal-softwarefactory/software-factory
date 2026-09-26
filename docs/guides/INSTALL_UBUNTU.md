# Instalar Kaanbal en Ubuntu Server

Guía paso a paso: del servidor limpio a una plataforma funcionando. Ejemplo con un PC Windows
como equipo de trabajo; en macOS o Linux son los mismos comandos con `ssh` y `ssh-keygen`.

> **Estado.** La validación integral en Ubuntu 26.04, el reinicio y la recuperación están
> pendientes (ver «Estado y limitaciones» en el [README](../../README.md)). Antes de cargar
> información importante, ejecuta las pruebas del final de esta guía.

Valores de ejemplo que debes sustituir: usuario `<usuario>`, IP `192.168.1.50`, alias `kaanbal-server`.

## 1. Preparar Ubuntu Server

Instala Ubuntu Server con OpenSSH Server y un usuario con `sudo`. Conecta el servidor a la red
local, preferiblemente por Ethernet. Obtén su IP con `hostname -I`. Comprueba RAM (mínimo 4 GB),
disco e Internet, y que cerrar la tapa no suspenda el equipo si es un portátil. Revisa los
servicios existentes antes de instalar o borrar nada.

## 2. Conectar por SSH

En PowerShell de tu PC: `ssh <usuario>@192.168.1.50`. Verifica la huella contra la consola del
servidor antes de aceptar la conexión inicial. Introduce tú la contraseña de Ubuntu; `exit`
regresa a tu PC.

Conserva el alias y la clave si ya funcionan. Para una clave nueva:

```powershell
Test-Path "$env:USERPROFILE/.ssh/kaanbal_ed25519"
ssh-keygen -t ed25519 -f "$env:USERPROFILE/.ssh/kaanbal_ed25519" -C "kaanbal-servidor"
```

Si `Test-Path` devuelve `True`, elige otro nombre: no sobrescribas una clave. Introduce
personalmente una frase de paso. Ed25519 usa OpenSSH y no necesita convertirse ni llamarse
`.pem`. El archivo sin extensión es privado; `.pub` es público. **Nadie —ni un asistente— debe
abrir la clave privada ni pedirte que la pegues.**

Instala solamente la pública; tú introduces la contraseña inicial:

```powershell
Get-Content "$env:USERPROFILE/.ssh/kaanbal_ed25519.pub" | ssh <usuario>@192.168.1.50 'umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; tr -d "\r" >> ~/.ssh/authorized_keys'
```

Añade a `%USERPROFILE%\.ssh\config`, sin reemplazar entradas ni duplicar alias:

```sshconfig
Host kaanbal-server
    HostName 192.168.1.50
    User <usuario>
    IdentityFile ~/.ssh/kaanbal_ed25519
    IdentitiesOnly yes
```

Comprueba `ssh kaanbal-server`. La frase de paso puede solicitarse. Si tienes el agente de
autenticación de OpenSSH en Windows, `ssh-add "$env:USERPROFILE/.ssh/kaanbal_ed25519"` desbloquea
la clave para tu sesión. La frase la introduces tú: no la elimines ni habilites `sudo` sin
contraseña para facilitar el acceso a un asistente.

Un asistente (Claude Code, Codex, Cursor) puede usar ese alias. Tú atiendes los prompts
interactivos y le confirmas que continúe. SSH y `sudo` son autenticaciones distintas: `sudo`
puede pedir la contraseña de Ubuntu aunque SSH use una clave.

## 3. Un comando de instalación

El repositorio y la revisión deben ser públicos. Dentro de `ssh kaanbal-server`:

```bash
( set -e; if ! command -v curl >/dev/null; then sudo apt-get update; sudo apt-get install -y curl ca-certificates; fi; revision=main; script=$(mktemp); trap 'rm -f "$script"' EXIT; curl --fail --show-error --location "https://raw.githubusercontent.com/kaanbal-softwarefactory/software-factory/${revision}/install.sh" --output "$script"; bash "$script" --ref "$revision" --lan )
```

Para reproducir exactamente una prueba, sustituye `main` por el SHA completo o la etiqueta que
quieras probar: `main` se mueve. `curl` debe terminar correctamente antes de ejecutar el archivo:
si el repositorio no fuera público, un 404 detiene el comando.

El bootstrap descarga el código en `~/kaanbal-source` y muestra el SHA. Con `--reset` descarga
primero la revisión y después elimina únicamente la instalación local administrada por Kaanbal,
incluidos sus datos y credenciales; no borra otros contenedores ni recursos externos. Tú
introduces `sudo` una vez cuando se solicite. Las credenciales van después, en el navegador.

Para instalar desde un fork o un espejo: `KAANBAL_REPO=https://github.com/<tú>/<fork>.git` antes
del comando `bash`.

Para reanudar un checkout válido ya descargado:

```bash
sudo bash ~/kaanbal-source/SOFTWARE_FACTORY/install.sh
```

Una descarga parcial se conserva para revisarla. `--reset` y `--dir` no pueden combinarse, para
impedir que una ruta arbitraria se elimine por accidente.

## 4. Abrir el navegador y completar credenciales

El modo `--lan` imprime una URL como `http://192.168.1.50:3000/?token=...`. Cópiala en el
navegador de un equipo de la misma red. **No compartas la URL**: el token permite controlar el
instalador hasta que confirmas el acceso y el servicio temporal se apaga.

Si el servidor ya está conectado a Tailscale, usa `--tailscale` en lugar de `--lan`. El
instalador valida la conexión, escucha únicamente en la IP `100.x.x.x` del servidor e imprime una
URL que abre cualquier dispositivo autorizado de la misma tailnet.

Si la red local no es de confianza, inicia con `--ssh-tunnel`. En ese modo, desde otra terminal
de PowerShell en tu PC, conserva abierto:

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:3000:127.0.0.1:3000 -L 127.0.0.1:4600:127.0.0.1:4600 -L 127.0.0.1:8080:127.0.0.1:8080 kaanbal-server
```

Abre la URL `http://localhost:3000/?token=...` que imprimió el instalador. No compartas ese token
ni capturas que lo incluyan. Loopback más SSH protege el transporte; no publiques esos puertos
HTTP. El 4600 sirve al asistente de IA y el 8080 al acceso provisional de Argo. Si un puerto está
ocupado, identifica a su dueño: no mates servicios desconocidos. Cerrar el túnel interrumpe el
navegador, pero el instalador sigue bajo systemd: reabre el túnel para retomar el progreso.

Crea el administrador y una contraseña larga. Completa los proveedores:

- **GitHub:** organización o usuario donde puedas crear repositorios. Token classic con `repo`,
  `workflow` y `read:org` según la organización. El SSO puede requerir autorización.
  `delete_repo` no es necesario para instalar. Usa un destino de prueba que no contenga repos del
  core de otra instalación.
- **Docker Hub:** usuario y token dedicado de lectura y escritura para publicar las imágenes.
- **Cloudflare:** para publicación, cuenta, zona/dominio y permisos de Tunnel y DNS indicados por
  el asistente. La zona debe pertenecer a la cuenta elegida.
- **Tailscale:** para VPN, OAuth del operador y tags/grants indicados por las validaciones.
  Autenticar el OAuth no prueba la conectividad: tu PC también necesita acceso a la tailnet.
- **IA:** opcional; puede configurarse después.

Los secretos los introduces en el navegador, nunca en un chat. El modo por archivo
`--unattended --env /ruta/segura/…` sigue disponible; esta guía usa el asistente web. Un asistente
de código nunca lee `.env` ni claves privadas. Corrige las validaciones fallidas antes de instalar y
conserva evidencia del progreso sin credenciales.

## 5. Verificación, Vault y reinicio

Comprueba el login real, los pods, las aplicaciones de Argo y una app de demostración por el canal
elegido. Confirma el cierre del instalador después de verificar el acceso administrativo.

Vault se desbloquea manualmente en esta versión. Conserva sus claves originales en un respaldo
protegido **fuera del servidor**. El token raíz es distinto de la clave de desbloqueo; ambos son
secretos. Una copia en el mismo clúster no es un respaldo externo. No generes una clave sustituta
ni reinicialices Vault para corregir un acceso.

El instalador guarda la recuperación en `/etc/kaanbal/vault-recovery.json`, con permisos 600. Para
preparar una copia que puedas descargar, ejecuta tú estos comandos en la sesión SSH (no imprimen su
contenido):

```bash
sudo install -D -m 600 -o "$USER" -g "$(id -gn)" /etc/kaanbal/vault-recovery.json "$HOME/.local/share/kaanbal/vault-recovery.json"
```

Desde PowerShell, descarga por SCP a una carpeta personal protegida:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE/kaanbal-backup" | Out-Null
scp kaanbal-server:.local/share/kaanbal/vault-recovery.json "$env:USERPROFILE/kaanbal-backup/vault-recovery.json"
```

Guarda esa copia en almacenamiento cifrado o en un gestor de secretos y limita quién accede a ella.
No la adjuntes a un chat ni la añadas a Git. Es material de recuperación, no una copia de los datos
de las aplicaciones.

Coordina un reinicio. Para desbloquear con el archivo protegido ya instalado:

```bash
sudo python3 ~/kaanbal-source/SOFTWARE_FACTORY/installer/vault_bootstrap.py --recover
```

El comando usa las claves originales sin imprimirlas y rechaza inicializar un Vault vacío. Si falta
el archivo, restaura primero el respaldo original a su ruta, con propietario root y modo 600. Un
asistente comprueba el estado sin leerlo. No pongas la clave como argumento de una orden que quede en
logs o en el historial. Este procedimiento no configura un auto-unseal externo. Respalda los datos y
prueba la restauración: las claves solas no recuperan los datos.

Documenta las pruebas antes de afirmar que está listo:

```text
PRUEBA: instalación Kaanbal — revisión <SHA>
FECHA:
PRECONDICIONES: Ubuntu, recursos, SSH y proveedores elegidos.
PASOS: instalación por el asistente web; login; app de demostración; reinicio coordinado;
       desbloqueo de Vault; persistencia y restauración de un respaldo.
RESULTADO ESPERADO: acceso y datos conservados; recuperación documentada.
RESULTADO OBTENIDO:
EVIDENCIA: comandos y URLs sin tokens, capturas sin credenciales.
APROBADO: sí/no; enumera las verificaciones pendientes.
```

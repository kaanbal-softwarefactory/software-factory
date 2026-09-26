# EMQX Edge — managed MQTT broker profile

## Qué es

Perfil **EMQX Edge** en Kaanbal: broker MQTT `config-only` (imagen oficial, sin repo de app), pensado para IoT local-first (ESP32, n8n, FastAPI) con canales simultáneos.

## Puertos

| Puerto | Uso | Internet |
|--------|-----|----------|
| 1883 MQTT TCP | ESP32, n8n interno, edge | **No** (Cloudflare no transporta MQTT TCP) |
| 8083 WebSocket | Browsers / WSS | Sí → `wss://mqtt-{app}.{domain}/mqtt` |
| 18083 Dashboard | Admin humano | No por defecto (LAN + Tailscale) |
| 8883 MQTT TLS | Reservado | Desactivado en esta versión |

## Canales (multi)

Un puerto puede tener varios a la vez:

- `internal` — `*.svc.cluster.local`
- `lan` — LoadBalancer K3s ServiceLB en IP del nodo
- `tailscale` — MagicDNS L4
- `public` — solo superficies HTTP/WS vía Cloudflare

Perfil Edge por defecto:

```text
mqtt:       internal + lan + tailscale
ws:         internal + lan + tailscale + public
dashboard:  internal + lan + tailscale
```

## Persistencia

StatefulSet + PVC `data` montado en `/opt/emqx/data` (5Gi). Reiniciar el pod no borra datos. El PVC lleva anotación `retain-on-delete`.

## Credenciales

Separadas (Vault → Secret):

- Dashboard admin
- `device` — clientes MQTT / ESP32
- `frontend` — solo lectura recomendada vía WSS

Bootstrap Job PostSync configura autenticación built-in de EMQX 5.

## Conexión rápida

**n8n / app en cluster:**

```text
mqtt://{app}.prod.svc.cluster.local:1883
user: device
```

**ESP32 en LAN:**

```text
mqtt://{LAN_IP}:1883
user: device
```

**Remoto autorizado (Tailscale):**

```text
mqtt://prod-{app}-mqtt.{tailnet}:1883
```

**Frontend público:**

```text
wss://mqtt-{app}.{domain}/mqtt
user: frontend
```

## Limitaciones v1

- No cluster multi-réplica EMQX
- No MQTT TLS 8883
- ACL fina por topic es best-effort en bootstrap
- LAN depende de ServiceLB de K3s y `KAANBAL_CLUSTER_LAN_IP` si la detección falla
- Gateway IoT dedicado (otro repo) queda fuera de este documento

# cloudflared — Cloudflare Tunnel (data plane)

El tier **público** de Kaanbal. `kaanbal-api` crea el túnel y las reglas de
ingress vía API de Cloudflare (`POST /api/v1/setup/tunnel`) — eso es el control
plane. Este Deployment es el data plane: consume el `TUNNEL_TOKEN` y mantiene
la conexión saliente al edge de Cloudflare.

## Por qué esto hace que una PC local sirva a internet

`cloudflared` solo abre conexiones **salientes** (QUIC :7844). No necesita IP
pública, puertos abiertos ni tocar el router. El wildcard `*.{dominio}` del
túnel apunta al ingress-controller del cluster, así que **toda app nueva queda
públicamente alcanzable sin reconfigurar el túnel**.

## Instalación del secret (única pieza manual)

El token vive en Mongo (`system_config.cloudflare_tunnel_token`) tras el setup.
Crear el Secret en cada cluster que deba servir tráfico público:

```bash
kubectl -n prod create secret generic cloudflared-secrets \
  --from-literal=TUNNEL_TOKEN='<cloudflare_tunnel_token>'
```

ArgoCD despliega este directorio automáticamente (ApplicationSet `apps/*/overlays/prod`).
Verificación: los pods reportan `/ready` 200 y el dashboard de Cloudflare
muestra el túnel como HEALTHY con 2 conexiones.

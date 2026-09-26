# ADR-002: Actualización del core de Kaanbal

Estado: **propuesto** — 2026-09-09

## Contexto

`software-factory` es público y contiene el instalador, el core (`kaanbal-api`,
`kaanbal-console`, `kaanbal-agent`), los templates y la baseline de infra. Hoy
ese repo alimenta **solo las instalaciones nuevas**. Una célula ya instalada no
tiene forma de recibir un cambio.

Peor: una célula no sabe **qué versión es**. `seed_platform()` no registra
ninguna procedencia — ni el commit del monorepo del que salió, ni el tag de cada
imagen. Sin procedencia no hay comparación posible con upstream, y sin snapshot
no hay retorno si un cambio sale mal.

Tampoco es cierto que baste con actualizar `infra-gitops`. Esa es la fuente de
verdad de **qué corre** (manifiestos y referencias de imagen), no del **código**:
las imágenes salen de los repos standalone. Un upgrade que solo toque
`infra-gitops` apuntaría a imágenes inexistentes y dejaría los pods en
`ImagePullBackOff`.

Actualizar una célula son tres cosas acopladas:

1. **Código** → repos standalone → imagen
2. **Manifiestos** → `infra-gitops` → ArgoCD sincroniza
3. **Estado** → migraciones de `system_config` / Mongo

Y hay un cuarto problema, el que rompe implementaciones ingenuas: **la API se
actualiza a sí misma**. Si `kaanbal-api` conduce su propio upgrade, el momento en
que promueve su nueva imagen mata el proceso que estaba conduciendo. La célula
queda a medio actualizar, sin nadie que verifique ni revierta. Es el modo de
falla más probable y el más difícil de diagnosticar.

## Decisión

### 1. La release es un artefacto inmutable, no un commit

Un upgrade no despliega "el último commit": despliega una **release publicada**.
Se publica como GitHub Release en `software-factory` con un manifiesto:

```json
{
  "version": "v1.2.0",
  "upstream_sha": "df8cb6e…",
  "components": {
    "kaanbal-api": {
      "image": "<tu-usuario-dockerhub>/kaanbal-api",
      "tag": "v1.2.0",
      "digest": "sha256:…",
      "repo_sha": "193cbb3…"
    }
  },
  "migrations": ["0002-seed-domains"],
  "notes": "…"
}
```

**Se fija por digest, no por tag.** Un tag puede moverse; un digest no. Es lo que
hace que dos células que instalan `v1.2.0` corran exactamente el mismo binario, y
lo que hace que el rollback sea exacto en vez de aproximado.

### 2. Canales

| Canal | Origen de la imagen | Para quién |
|---|---|---|
| `stable` | Release publicada por el autor | La mayoría. Upgrade en segundos: solo cambian referencias. |
| `dev` | Release de una rama del autor | El autor, probando en su célula de laboratorio. |
| `custom` | La célula construye con Kaniko desde su propio repo | Quien tunea localmente. |

El canal no lo elige el usuario a ciegas: una célula entra en `custom`
**automáticamente** cuando se detecta deriva.

### 3. Deriva (drift)

Para cada componente se compara el HEAD del repo standalone contra el `repo_sha`
de la release aplicada. Si difieren, ese componente está modificado localmente.
La consola lo muestra como estado, no como error: tunear es legítimo.

Ante un upgrade con deriva, la célula ofrece tres salidas explícitas —
**adoptar** upstream descartando lo local, **rebasar** lo local sobre upstream, o
**quedarse**. Nunca se elige por el usuario: perder un cambio local en silencio es
inaceptable.

### 4. Contribuir de vuelta

La célula ya tiene un token de GitHub. `POST /core/propose` abre un PR upstream
desde el componente derivado: forkea `software-factory`, aplica el diff en la
ruta del monorepo (`SOFTWARE_FACTORY/<componente>/`) y abre el PR describiendo la
célula (versión, componente, deriva).

Si el autor lo acepta y publica una release, quien lo propuso ve una versión
nueva que **contiene su propio cambio**, y al adoptarla vuelve a `stable` sin
deriva. Ese es el ciclo completo: tunear → proponer → volver al carril común.

### 5. El upgrade lo ejecuta un Job, no la API

**Esta es la decisión central.** El upgrade corre como un `Job` de Kubernetes
efímero (`kaanbal-upgrade-<id>`) creado por la API. El Job es quien promueve,
espera y verifica; la API solo lo crea y luego reporta su progreso leyendo el
estado que el Job escribe en Mongo.

Así, cuando le toca a `kaanbal-api` recibir su nueva imagen, el proceso que
conduce el upgrade **no es el que muere**. La consola puede perder el backend
unos segundos y reconectarse; el Job sigue vivo y verifica el resultado.

### 6. La transacción

```
lock → preflight → snapshot → migrar → promover → esperar rollout → verificar
                        └──────────────── rollback ────────────────┘
```

- **lock**: single-flight. Dos upgrades simultáneos dejarían `infra-gitops` en un
  estado que ninguno de los dos sabe revertir.
- **snapshot**: digests actuales de cada componente + SHA de `infra-gitops`. Es
  el punto de retorno.
- **promover**: commit único a `infra-gitops` con todos los componentes. Un
  commit por componente daría ventanas donde corren versiones mezcladas.
- **verificar**: ArgoCD `Synced/Healthy` + `/health` de la API. Si no ocurre
  dentro de la ventana, **rollback automático**.
- **rollback**: restaura los digests del snapshot. Barato y exacto: las imágenes
  son inmutables y siguen publicadas. No se reconstruye nada.

### 6b. Un solo dueño de la promoción

Los repos standalone traen un workflow de GitHub Actions que construye y
promueve en cada push. Si el upgrade empuja código y además promueve, hay **dos
actores** escribiendo tags en `infra-gitops`. Se observó en laboratorio: CI promovió
antes que la transacción, que encontró el trabajo ya hecho.

Ese resultado fue correcto por suerte. El caso real es peor: el upgrade falla,
revierte, y minutos después CI termina y **vuelve a promover la versión que el
rollback acaba de retirar**.

Regla: los commits de sync de un upgrade llevan `[skip ci]`. La transacción es la
única que construye y promueve. CI queda para los push directos al repo
standalone, que es el flujo `custom`.

### 7. Migraciones: expand/contract, nunca destructivas en el mismo release

El rollback de código es exacto; el de esquema no lo es. Por eso las migraciones
son **idempotentes, versionadas y compatibles hacia atrás dentro de una release**:
una release que agrega un campo no puede además eliminar el viejo. La eliminación
va en la release siguiente, cuando ya no hay a qué volver.

Se registran en `core_migrations` para no repetirse.

## Consecuencias

- El instalador debe escribir procedencia (`system_config.core_release`) o la
  célula nace sin saber qué es. Es requisito de todo lo demás.
- Publicar una release deja de ser un push: es construir, fijar digests y
  publicar el manifiesto. Debe ser un workflow, no un paso manual.
- Las células necesitan salida a la API de GitHub para consultar releases.
- Una célula en `custom` no recibe `stable` automáticamente; debe resolver la
  deriva primero. Es deliberado.

## Alternativas rechazadas

- **Cada célula construye siempre desde el monorepo.** Funciona con la maquinaria
  actual (Kaniko ya está), pero cada upgrade tarda minutos, carga el nodo, y dos
  células podrían obtener imágenes distintas del mismo commit. Queda solo para
  `custom`.
- **Solo releases del autor, sin build local.** Máxima predictibilidad, pero mata
  el tuneo local y con él el flujo de contribución.
- **Actualizar solo `infra-gitops`.** No alcanza: el código no vive ahí.
- **La API conduce su propio upgrade.** Es lo natural de escribir y lo que deja
  células a medio actualizar sin testigo.
- **Upgrade automático.** Un cambio malo llegaría a todos los clientes sin que
  nadie lo intercepte. El disparo es manual y con changelog a la vista.

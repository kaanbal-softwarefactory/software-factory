# Business Base: candidato de stack

Rama: `codex/business-base-stack`, basada en main f036ad2.

Solicitud: lanzar la base mediante Kaanbal, automatizar configuraciones repetidas
y conservar el lanzamiento de apps individuales. Se detectó que el catálogo y
el deployer aún no tenían el contrato de identidad/roles/bootstrap requerido.

Implementación: stack `business-base-demo` con tres apps ordenadas (base,
identidad y app). La app opera también worker y correo capturado internamente.
Presets servicios/barbería y marca; grupo y responsable inicial por lanzador.
Código de copia fijado al SHA instalado, sin interpolar fuentes.

Seguridad operativa: Vault CAS, Secrets runtime fuera de Git, privilegios
separados por contenedor, Keycloak start, API admin interna, NetworkPolicies,
sin token de ServiceAccount en cargas; Role de entrega de secretos get/create
en prod, ubicado en rbac.yaml estático para que se aplique durante upgrade.

Verificado: API 577 OK (1 skipped), 13 contratos de secretos/stack/Kustomize;
consola compila, 7 pruebas unitarias de negocio, build Next/Docker, 33 pruebas
GitOps. Compose de aceptación con Keycloak producción y PostgreSQL reales:
bootstrap repetido sin duplicados, sujetos estables, membresía owner y RLS.
Primer intento detectó permisos del volumen de prueba; corregido mediante
volumen de secretos acotado al harness. Acceptance pasó después.

Sin mutaciones en la célula remota. Conector GitHub push=false y gh sin sesión;
no se creó PR ni se publicó la rama. No se marca demo remota lista ni candidato
ready. Requiere merge+upgrade y aceptación HTTPS en la célula antes de lanzarse
con plan aprobado. Contrato y límites: business-base/KAANBAL_STACK.md.

PRUEBA: Business Base stack — bootstrap y GitOps
FECHA: 2026-10-21
PRECONDICIONES: Docker local, Node 24, dependencias API, kubectl para Kustomize.
PASOS: suites API/GitOps, build consola/app, aceptación aislada de bootstrap.
RESULTADO ESPERADO: credenciales separadas, YAML válido, bootstrap repetible y RLS.
RESULTADO OBTENIDO: verificaciones locales aprobadas; célula remota pendiente.
EVIDENCIA: test_business_stack.py y tests/managed-bootstrap.mjs.
APROBADO: sí para candidato local; no para aceptación remota.

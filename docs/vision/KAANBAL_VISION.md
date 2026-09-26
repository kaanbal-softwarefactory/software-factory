# Kaanbal — Visión

> Una plataforma auto-hospedada, de código abierto y con criterio propio, para llevar una idea
> desde el código hasta un servicio en producción —en tu propio servidor— sin tener que ser un
> experto en infraestructura.

## El problema

Publicar una aplicación con calidad de producción exige un repositorio, CI, imágenes, Kubernetes,
DNS, TLS, secretos, una forma segura de exponerla y alguien que lo mantenga al día. Cada pieza
tiene su herramienta y casi ninguna conversa con las demás. Quien no es especialista en
infraestructura termina pegando comandos que no entiende, o alquilando una plataforma ajena.

## La propuesta

Kaanbal une esas piezas detrás de una consola y una API. Instalas la plataforma con un comando en
tu propio hardware y, desde ahí, lanzas una aplicación, una base de datos o un stack completo
sabiendo que:

- cada cambio queda en Git y se despliega de forma reproducible;
- los secretos nunca viajan por Git;
- la exposición —red local, VPN o Internet— es una decisión explícita por aplicación;
- puedes actualizar la propia plataforma sin miedo, porque cada actualización se verifica y se
  revierte sola si falla.

## Principios

1. **GitOps primero.** El estado deseado vive en Git. Lo que corre es lo que dicen los manifiestos,
   no lo que alguien tecleó en un servidor.
2. **Secretos fuera de Git.** Se generan por aplicación y viven en Vault.
3. **Local primero, híbrido después.** Corre en tu hardware. Una aplicación puede ser interna,
   privada por VPN o pública, y la plataforma puede crecer hacia varios sitios.
4. **API primero.** Todo lo que hace la consola lo puede hacer una API con permisos acotados.
5. **Agentes gobernados.** Los asistentes de IA son ciudadanos de primera clase, pero con tokens
   propios, alcance mínimo, sin acceso a valores secretos y con aprobación humana para actuar.
6. **Reproducible.** Un comando instala la plataforma completa, y un instalador idempotente puede
   repetirse.
7. **Extensible.** Una plantilla es la unidad de contribución de la comunidad.

## Dónde estamos

Hoy Kaanbal es una plataforma de aplicaciones completa: instalador, consola, API, plantillas,
stacks, varios dominios, control de exposición, control de acceso, actualizaciones del core y un
servidor MCP. Ver el [README](../../README.md) y el [changelog](../../CHANGELOG.md).

## Hacia dónde queremos ir

El [blueprint](../../SOFTWARE_FACTORY/BLUEPRINT.md) describe una plataforma unificada de
**aplicaciones, MLOps y flotas IoT** con un mismo plano de control y un mismo concepto de *site*
(un lugar donde corre cómputo: un VPS, un PC local, un gateway de un cliente). El registro de
sites y los vínculos entre servicios existen; el resto es dirección, no compromiso.

## A quién le sirve

A quien ya sabe desarrollar —a menudo con ayuda de asistentes de IA— un frontend, una API y una
base de datos, y quiere ponerlos en producción, integrar mensajería o automatización, y mantenerlos,
sin convertirse en operador de clústeres.

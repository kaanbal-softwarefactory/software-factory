"""Versioned discovery for a stable MCP bridge; each action still traverses ACL."""


def tool(name, description, method, path, permission, *, path_args=(), query_args=(), body_args=(), required=(), elevated=False, extra_permissions=()):
    return dict(name=name, description=description, method=method, path=path, permission=permission,
                path_args=list(path_args), query_args=list(query_args), body_args=list(body_args), required=list(required),
                elevated=elevated, extra_permissions=list(extra_permissions))


TOOLS = [
    tool("platform_capabilities", "Descubrir capacidades de autonomía disponibles para este token y sus parámetros.", "GET", "/autonomy/capabilities", "autonomy.tools.view"),
    tool("execute_app_command", "Ejecutar un comando en la app; puede cambiar datos. Requiere razón y token crítico.", "POST", "/autonomy/apps/{app_name}/execute", "autonomy.apps.execute", path_args=["app_name"], body_args=["env", "command", "timeout_seconds", "reason"], required=["app_name", "command", "reason"], elevated=True),
    tool("execute_node_command", "Ejecutar como root en un nodo autorizado. La operación retorna un identificador para consultar su resultado.", "POST", "/autonomy/nodes/{node}/execute", "autonomy.host.execute", path_args=["node"], body_args=["command", "timeout_seconds", "reason"], required=["node", "command", "reason"], elevated=True),
    tool("get_operation", "Consultar estado y resultado de una operación del mismo token.", "GET", "/autonomy/operations/{operation_id}", "autonomy.tools.view", path_args=["operation_id"], required=["operation_id"]),
    tool("open_app_workspace", "Preparar un contenedor efímero para una app. Esperar Running y llamar initialize_workspace.", "POST", "/autonomy/workspaces", "autonomy.workspaces.manage", body_args=["app", "env", "reason"], required=["app", "reason"]),
    tool("open_core_workspace", "Preparar una contribución al repo público de Kaanbal; siempre se revisa por un owner.", "POST", "/autonomy/core/workspaces", "autonomy.core.contribute", body_args=["env", "reason"], required=["reason"], extra_permissions=["autonomy.workspaces.manage"]),
    tool("get_workspace", "Consultar el workspace y la fase de su contenedor.", "GET", "/autonomy/workspaces/{workspace_id}", "autonomy.workspaces.manage", path_args=["workspace_id"], required=["workspace_id"]),
    tool("initialize_workspace", "Descargar el código del commit registrado, sin credenciales en el contenedor.", "POST", "/autonomy/workspaces/{workspace_id}/initialize", "autonomy.workspaces.manage", path_args=["workspace_id"], required=["workspace_id"]),
    tool("workspace_files", "Sin path, listar archivos; con path, leer un archivo de texto.", "GET", "/autonomy/workspaces/{workspace_id}/files", "autonomy.workspaces.manage", path_args=["workspace_id"], query_args=["path"], required=["workspace_id"]),
    tool("write_workspace_file", "Guardar texto UTF-8; content=null elimina el archivo del workspace.", "POST", "/autonomy/workspaces/{workspace_id}/files", "autonomy.workspaces.manage", path_args=["workspace_id"], body_args=["path", "content"], required=["workspace_id", "path", "content"]),
    tool("workspace_diff", "Leer cambios completos y digest requerido antes de publicar un PR.", "GET", "/autonomy/workspaces/{workspace_id}/diff", "autonomy.workspaces.manage", path_args=["workspace_id"], required=["workspace_id"]),
    tool("run_workspace_command", "Ejecutar una validación o editar en el contenedor sin credenciales de plataforma.", "POST", "/autonomy/workspaces/{workspace_id}/execute", "autonomy.workspaces.manage", path_args=["workspace_id"], body_args=["command", "timeout_seconds", "reason"], required=["workspace_id", "command", "reason"]),
    tool("publish_workspace_pr", "Publicar cambios revisados en una rama y PR. expected_digest debe salir de workspace_diff.", "POST", "/autonomy/workspaces/{workspace_id}/pull-request", "autonomy.changes.propose", path_args=["workspace_id"], body_args=["title", "body", "expected_digest"], required=["workspace_id", "title", "body", "expected_digest"], extra_permissions=["autonomy.workspaces.manage"]),
    tool("merge_app_pr", "Integrar un PR de app listo en GitHub. Kaanbal core requiere merge humano.", "POST", "/autonomy/workspaces/{workspace_id}/merge", "autonomy.changes.merge", path_args=["workspace_id"], body_args=["expected_sha"], required=["workspace_id", "expected_sha"], elevated=True, extra_permissions=["autonomy.workspaces.manage"]),
    tool("close_workspace", "Destruir el contenedor temporal después de publicar.", "DELETE", "/autonomy/workspaces/{workspace_id}", "autonomy.workspaces.manage", path_args=["workspace_id"], required=["workspace_id"]),
    tool("platform_updates", "Consultar actualizaciones disponibles.", "GET", "/core/updates", "core.updates.view"),
    tool("platform_upgrade", "Actualizar la plataforma desde upstream después del merge; devuelve un Job que sobrevive al reinicio de la API.", "POST", "/core/upgrade", "core.updates.apply", body_args=["ref"]),
    tool("platform_upgrade_status", "Consultar progreso del Job de actualización.", "GET", "/core/upgrade", "core.updates.view", query_args=["name"]),
]


def capabilities_for(principal):
    return {"protocol_version": 1, "tools": [t for t in TOOLS if principal.can(t["permission"])
        and all(principal.can(p) for p in t["extra_permissions"])
        and (not t["elevated"] or not principal.via_token or principal.elevated)],
        "instructions": "Los permisos ACL y la política se comprueban al ejecutar. Tras actualizar Kaanbal, vuelve a descubrir herramientas; invoke_platform_tool puede usarlas sin reinstalar el cliente MCP."}

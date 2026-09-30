"""Agent operations with ACL, resource policy and per-token attribution."""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db import get_db
from app.services import autonomy as service
from app.services.autonomy_policy import AutonomyError, resource_name, node_name


class AutonomyRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                return await handler(request)
            except AutonomyError as exc:
                raise HTTPException(exc.status, str(exc))
            except (HTTPException, RequestValidationError):
                raise
            except Exception:
                raise HTTPException(502, "La operación no pudo completarse. Consulta su estado antes de repetir una acción.")
        return guarded


router = APIRouter(route_class=AutonomyRoute)


def principal(request):
    result = getattr(request.state, "principal", None)
    if result is None:
        raise HTTPException(401, "Sesión no resuelta")
    return result


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grant(StrictModel):
    username: str = Field(..., min_length=1, max_length=80)
    token_id: Optional[str] = None
    apps: List[str] = Field(default_factory=list, max_length=100)
    environments: List[str] = Field(default_factory=list, max_length=10)
    nodes: List[str] = Field(default_factory=list, max_length=30)
    core: bool = False
    expires_at: Optional[datetime] = None

    @field_validator("apps", "environments")
    @classmethod
    def exact_names(cls, values):
        for value in values:
            try:
                resource_name(value)
            except AutonomyError:
                raise ValueError("Usa nombres exactos, sin comodines.")
        return values

    @field_validator("nodes")
    @classmethod
    def exact_nodes(cls, values):
        for value in values:
            try:
                node_name(value)
            except AutonomyError:
                raise ValueError("Usa nombres DNS exactos de nodos, sin comodines.")
        return values

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("La expiración requiere zona horaria.")
        return value


class Policy(StrictModel):
    enabled: bool = False
    runtime_enabled: bool = False
    workspace_enabled: bool = False
    host_enabled: bool = False
    merge_enabled: bool = False
    workbench_image: str = Field(default="", max_length=300)
    core_fork: str = Field(default="", max_length=150)
    workspace_lifetime_seconds: int = Field(default=3600, ge=300, le=14400)
    grants: List[Grant] = Field(default_factory=list, max_length=100)


class PolicyUpdate(StrictModel):
    policy: Policy
    admin_username: str
    admin_password: str = Field(..., min_length=1, max_length=1024, repr=False)


class Command(StrictModel):
    command: str = Field(..., min_length=1, max_length=16384)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    reason: str = Field(..., min_length=5, max_length=500)


class AppCommand(Command):
    env: str = Field(default="prod", max_length=63)


class OpenWorkspace(StrictModel):
    app: str = Field(..., min_length=1, max_length=63)
    env: str = Field(default="prod", max_length=63)
    reason: str = Field(..., min_length=5, max_length=500)


class OpenCore(StrictModel):
    env: str = Field(default="prod", max_length=63)
    reason: str = Field(..., min_length=5, max_length=500)


class FileWrite(StrictModel):
    path: str = Field(..., min_length=1, max_length=500)
    content: Optional[str] = Field(default=None, max_length=1024 * 1024)


class PullRequest(StrictModel):
    title: str = Field(..., min_length=5, max_length=200)
    body: str = Field(..., min_length=5, max_length=20000)
    expected_digest: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class Merge(StrictModel):
    expected_sha: str = Field(..., pattern=r"^[0-9a-f]{40}$")


@router.get("/capabilities")
async def capabilities(request: Request):
    from app.services.autonomy_catalog import capabilities_for
    result = capabilities_for(principal(request))
    schema = request.app.openapi()
    definitions = schema.get("components", {}).get("schemas", {})
    enriched = []
    for spec in result["tools"]:
        route = schema.get("paths", {}).get("/api/v1" + spec["path"], {}).get(spec["method"].lower(), {})
        body = route.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if "$ref" in body:
            body = definitions.get(body["$ref"].rsplit("/", 1)[-1], {})
        properties = {p["name"]: p.get("schema", {"type": "string"}) for p in route.get("parameters", [])}
        properties.update(body.get("properties", {}))
        for argument in spec["path_args"] + spec["query_args"] + spec["body_args"]:
            properties.setdefault(argument, {"type": "string"})
        enriched.append({**spec, "input_schema": {"type": "object", "properties": properties,
            "required": spec["required"], "additionalProperties": False}})
    return {**result, "tools": enriched}


@router.get("/policy")
async def get_policy():
    return Policy.model_validate((await service.configuration()).get("autonomy", {})).model_dump(mode="json")


@router.put("/policy")
async def update_policy(body: PolicyUpdate, request: Request):
    from app.services.step_up import confirm
    actor = principal(request)
    await confirm(actor, body.admin_username, body.admin_password, action="autonomy.policy.update")
    policy = body.policy.model_dump(mode="json")
    async with service.audit(actor, "policy.update", "autonomy", "Modificar la política de autonomía"):
        await get_db().system_config.update_one({"_id": "main"}, {"$set": {"autonomy": policy}}, upsert=True)
    return policy


@router.post("/apps/{app_name}/execute")
async def execute_app(app_name: str, body: AppCommand, request: Request):
    return await service.execute_app(principal(request), app_name, body.env, body.command, body.timeout_seconds, body.reason)


@router.post("/nodes/{node}/execute", status_code=202)
async def execute_node(node: str, body: Command, request: Request):
    return await service.execute_host(principal(request), node, body.command, body.timeout_seconds, body.reason)


@router.get("/operations/{operation_id}")
async def get_operation(operation_id: str, request: Request):
    return await service.operation(principal(request), operation_id)


@router.post("/workspaces", status_code=201)
async def open_workspace(body: OpenWorkspace, request: Request):
    return await service.open_workspace(principal(request), target="app", app=body.app, env=body.env, reason=body.reason)


@router.post("/core/workspaces", status_code=201)
async def open_core_workspace(body: OpenCore, request: Request):
    return await service.open_workspace(principal(request), target="core", app="", env=body.env, reason=body.reason)


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str, request: Request):
    import asyncio
    ws, _ = await service.workspace(principal(request), workspace_id, live=False)
    result = service.public_workspace(ws)
    if ws["state"] not in {"expired", "closed", "failed"}:
        result["pod_phase"] = await asyncio.to_thread(service.cluster.workspace_phase, ws["pod"])
    return result


@router.post("/workspaces/{workspace_id}/initialize")
async def initialize_workspace(workspace_id: str, request: Request):
    return await service.initialize(principal(request), workspace_id)


@router.get("/workspaces/{workspace_id}/files")
async def read_files(workspace_id: str, request: Request, path: Optional[str] = None):
    return await service.files(principal(request), workspace_id, path=path)


@router.post("/workspaces/{workspace_id}/files")
async def write_file(workspace_id: str, body: FileWrite, request: Request):
    return await service.files(principal(request), workspace_id, path=body.path, content=body.content, write=True)


@router.get("/workspaces/{workspace_id}/diff")
async def workspace_diff(workspace_id: str, request: Request):
    return await service.diff(principal(request), workspace_id)


@router.post("/workspaces/{workspace_id}/execute")
async def execute_workspace(workspace_id: str, body: Command, request: Request):
    return await service.run_workspace(principal(request), workspace_id, body.command, body.timeout_seconds, body.reason)


@router.post("/workspaces/{workspace_id}/pull-request")
async def publish_workspace(workspace_id: str, body: PullRequest, request: Request):
    return await service.publish(principal(request), workspace_id, body.title, body.body, body.expected_digest)


@router.post("/workspaces/{workspace_id}/merge")
async def merge_workspace(workspace_id: str, body: Merge, request: Request):
    return await service.merge(principal(request), workspace_id, body.expected_sha)


@router.delete("/workspaces/{workspace_id}")
async def close_workspace(workspace_id: str, request: Request):
    return await service.close(principal(request), workspace_id)

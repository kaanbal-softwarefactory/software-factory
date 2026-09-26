from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks
from typing import List, Dict, Optional
from pydantic import BaseModel
from datetime import datetime
import logging
import json

from app.services.template_service import TemplateService
from app.routers.auth import get_current_active_user
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])
template_service = TemplateService()


# ============ MODELS ============

class CustomTemplateCreate(BaseModel):
    """Modelo para crear un template personalizado"""
    id: str  # slug único, ej: "vue3-dashboard"
    name: str
    description: str
    category: str  # frontend, backend, fullstack
    icon: str = "cube"
    stack: List[str] = []
    base_template: Optional[str] = None  # Si es variante de otro
    environments: List[str] = ["dev", "prod"]
    creation_modes: List[str] = ["scaffold", "empty"]
    # Pipeline config
    dockerfile_template: Optional[str] = None
    pipeline_template: Optional[str] = None
    # K8s config
    default_port: int = 80
    default_replicas: int = 1
    health_check_path: str = "/"


class TemplateUsageStats(BaseModel):
    """Estadísticas de uso de un template"""
    template_id: str
    total_apps: int
    apps_by_environment: Dict[str, int]
    recent_deployments: int  # Últimos 30 días


# ============ CORE ENDPOINTS ============

@router.get("", response_model=List[Dict])
async def list_templates(
    category: Optional[str] = None,
    status: Optional[str] = None,
    include_custom: bool = True
):
    """
    Get all available application templates.
    
    Query params:
    - category: Filter by category (frontend, backend, database, workflow, etc.)
    - status: Filter by status (ready, coming_soon, beta)
    - include_custom: Include custom/user-created templates
    
    Returns a list of templates with metadata including:
    - id: Unique template identifier
    - name: Display name
    - description: Template description
    - icon: Icon identifier
    - category: frontend/backend/database/workflow/etc.
    - stack: Array of technologies used
    - is_custom: Whether it's a user-created template
    - status: ready/coming_soon/beta
    """
    try:
        # Get standard templates with filters
        templates = await template_service.get_templates(category=category, status=status)
        
        # Include custom templates from DB
        if include_custom:
            db = get_db()
            query = {}
            if category:
                query["category"] = category
            
            custom_templates = await db.custom_templates.find(query).to_list(100)
            for ct in custom_templates:
                ct["_id"] = str(ct["_id"])
                ct["is_custom"] = True
                ct["source"] = "custom"
                templates.append(ct)
        
        logger.info(f"Returning {len(templates)} templates (category={category}, status={status})")
        return templates
    except Exception as e:
        logger.error(f"Error fetching templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/refresh")
async def refresh_templates(current_user = Depends(get_current_active_user)):
    """
    Force refresh the templates cache from the repository.
    Requires authentication.
    """
    success = await template_service.refresh_cache()
    if success:
        templates = await template_service.get_templates()
        return {
            "message": "Templates cache refreshed successfully",
            "template_count": len(templates),
            "templates": [t["id"] for t in templates]
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to refresh templates from repository"
        )


# ============ CREATION MODES (must be before /{template_id}) ============

@router.get("/creation-modes")
async def get_creation_modes():
    """
    Get all available creation modes with descriptions.
    """
    return {
        "scaffold": {
            "name": "🏗️ Scaffold",
            "description": "Create from official CLI with latest LTS versions",
            "how_it_works": "Runs the official create command (pnpm dlx create-vite@latest, pnpm create vue@latest, etc) to generate a fresh project",
            "best_for": "New projects that should use the latest best practices",
            "requires": "Nothing - we handle everything"
        },
        "empty": {
            "name": "📁 Empty Repository",
            "description": "Empty repo with README and pipeline template - you add your code",
            "how_it_works": "Creates a Bitbucket repo with basic structure. You clone, add your code, and push.",
            "best_for": "When you have existing code or want full control",
            "requires": "You need to push your code manually"
        },
        "upload": {
            "name": "📤 Upload / Import",
            "description": "Upload a ZIP file or connect an existing repository",
            "how_it_works": "We import your code, analyze it, and configure the pipeline automatically",
            "best_for": "Migrating existing projects",
            "requires": "Your existing code or repo URL"
        },
        "config-only": {
            "name": "⚙️ Config Only",
            "description": "No code repository - deploys official Docker images",
            "how_it_works": "Creates only Kubernetes manifests in infra-gitops. Uses official images like mongo, postgres, n8n.",
            "best_for": "Databases, pre-built services, stateful apps",
            "requires": "Nothing - uses official images"
        }
    }


# ============ TEMPLATE DETAILS ============

@router.get("/{template_id}")
async def get_template(template_id: str):
    """
    Get detailed information about a specific template.
    
    Includes all metadata plus:
    - variables: Template variables for customization
    - placeholders: Placeholders to replace during deployment
    - pipeline_variables: Required Bitbucket pipeline variables
    - environments: Supported deployment environments
    """
    # First check custom templates
    db = get_db()
    custom = await db.custom_templates.find_one({"id": template_id})
    if custom:
        custom["_id"] = str(custom["_id"])
        custom["is_custom"] = True
        return custom
    
    # Then check standard templates
    template = await template_service.get_template_details(template_id)
    if not template:
        raise HTTPException(
            status_code=404, 
            detail=f"Template '{template_id}' not found"
        )
    template["is_custom"] = False
    return template


# ============ CUSTOM TEMPLATES ============

@router.post("/custom")
async def create_custom_template(
    template: CustomTemplateCreate,
    current_user = Depends(get_current_active_user)
):
    """
    Create a new custom template.
    
    Custom templates start in 'draft' status and must pass validation
    before they can be used to create apps.
    """
    db = get_db()
    
    # Check if ID already exists
    existing = await db.custom_templates.find_one({"id": template.id})
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Template with id '{template.id}' already exists"
        )
    
    # Also check standard templates
    standard = await template_service.get_template_details(template.id)
    if standard:
        raise HTTPException(
            status_code=400,
            detail=f"Template id '{template.id}' conflicts with a standard template"
        )
    
    template_doc = {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "icon": template.icon,
        "stack": template.stack,
        "base_template": template.base_template,
        "environments": template.environments,
        "creation_modes": template.creation_modes,
        "dockerfile_template": template.dockerfile_template,
        "pipeline_template": template.pipeline_template,
        "default_port": template.default_port,
        "default_replicas": template.default_replicas,
        "health_check_path": template.health_check_path,
        # Status de validación
        "status": "draft",  # draft, validating, validation_failed, ready
        "test_apps": [],
        "validation_started_at": None,
        "validation_completed_at": None,
        # Metadata
        "created_at": datetime.utcnow(),
        "created_by": current_user.username,
        "version": "1.0.0",
        "is_published": False
    }
    
    result = await db.custom_templates.insert_one(template_doc)
    template_doc["_id"] = str(result.inserted_id)
    
    logger.info(f"Custom template '{template.id}' created by {current_user.username}")
    
    return {
        "message": f"Custom template '{template.name}' created successfully",
        "status": "draft",
        "next_step": "Start validation to test this template",
        "template": template_doc
    }


@router.put("/custom/{template_id}")
async def update_custom_template(
    template_id: str,
    template: CustomTemplateCreate,
    current_user = Depends(get_current_active_user)
):
    """
    Update an existing custom template.
    """
    db = get_db()
    
    existing = await db.custom_templates.find_one({"id": template_id})
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Custom template '{template_id}' not found"
        )
    
    update_data = {
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "icon": template.icon,
        "stack": template.stack,
        "base_template": template.base_template,
        "variables": template.variables,
        "environments": template.environments,
        "updated_at": datetime.utcnow(),
        "updated_by": current_user.username
    }
    
    # Increment version
    current_version = existing.get("version", "1.0.0")
    parts = current_version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    update_data["version"] = ".".join(parts)
    
    await db.custom_templates.update_one(
        {"id": template_id},
        {"$set": update_data}
    )
    
    return {
        "message": f"Template '{template_id}' updated",
        "new_version": update_data["version"]
    }


@router.delete("/custom/{template_id}")
async def delete_custom_template(
    template_id: str,
    current_user = Depends(get_current_active_user)
):
    """
    Delete a custom template.
    
    Note: This won't affect apps already created with this template.
    """
    db = get_db()
    
    existing = await db.custom_templates.find_one({"id": template_id})
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Custom template '{template_id}' not found"
        )
    
    # Check if any apps use this template
    apps_using = await db.apps.count_documents({"template_id": template_id})
    
    await db.custom_templates.delete_one({"id": template_id})
    
    logger.info(f"Custom template '{template_id}' deleted by {current_user.username}")
    
    return {
        "message": f"Template '{template_id}' deleted",
        "warning": f"{apps_using} existing apps were using this template" if apps_using > 0 else None
    }


@router.post("/custom/{template_id}/publish")
async def publish_custom_template(
    template_id: str,
    current_user = Depends(get_current_active_user)
):
    """
    Publish a custom template, making it available for all users.
    """
    db = get_db()
    
    existing = await db.custom_templates.find_one({"id": template_id})
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Custom template '{template_id}' not found"
        )
    
    await db.custom_templates.update_one(
        {"id": template_id},
        {"$set": {
            "is_published": True,
            "published_at": datetime.utcnow(),
            "published_by": current_user.username
        }}
    )
    
    return {"message": f"Template '{template_id}' is now published"}


# ============ TEMPLATE STATS ============

@router.get("/{template_id}/stats")
async def get_template_stats(template_id: str):
    """
    Get usage statistics for a template.
    
    Returns:
    - Total apps using this template
    - Apps by environment
    - Recent deployments (last 30 days)
    """
    db = get_db()
    
    # Get all apps using this template
    apps = await db.apps.find({"template_id": template_id}).to_list(1000)
    
    # Count by environment
    env_counts = {}
    for app in apps:
        for env in app.get("environments", []):
            env_counts[env] = env_counts.get(env, 0) + 1
    
    # Recent deployments (apps created in last 30 days)
    from datetime import timedelta
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent = await db.apps.count_documents({
        "template_id": template_id,
        "created_at": {"$gte": thirty_days_ago}
    })
    
    return {
        "template_id": template_id,
        "total_apps": len(apps),
        "apps_by_environment": env_counts,
        "recent_deployments": recent
    }


# ============ TEMPLATE CATEGORIES ============

@router.get("/categories/list")
async def list_categories():
    """
    Get all available template categories with descriptions.
    """
    return [
        {
            "id": "frontend",
            "name": "Frontend",
            "description": "Client-side web applications",
            "icon": "window",
            "examples": ["Vue.js SPA", "React App", "Landing Page"],
            "creation_modes": ["scaffold", "empty", "upload"],
            "scaffold_options": [
                {"id": "vue3", "name": "Vue 3 + Vite", "command": "pnpm create vue@latest"},
                {"id": "react", "name": "React + Vite", "command": "pnpm dlx create-vite@latest {{APP_NAME}} --template react-ts"},
                {"id": "vite", "name": "Vite (vanilla)", "command": "pnpm dlx create-vite@latest {{APP_NAME}}"}
            ]
        },
        {
            "id": "backend",
            "name": "Backend",
            "description": "Server-side APIs and services",
            "icon": "server",
            "examples": ["FastAPI", "Node.js Express", "Go Service"],
            "creation_modes": ["scaffold", "empty", "upload"],
            "scaffold_options": [
                {"id": "fastapi", "name": "FastAPI", "command": None},
                {"id": "express", "name": "Express.js", "command": "pnpm dlx express-generator"},
                {"id": "nestjs", "name": "NestJS", "command": "pnpm dlx @nestjs/cli new"}
            ]
        },
        {
            "id": "fullstack",
            "name": "Full Stack",
            "description": "Complete applications with frontend and backend",
            "icon": "layers",
            "examples": ["Next.js", "Nuxt.js", "Django + React"],
            "creation_modes": ["scaffold", "empty"],
            "scaffold_options": [
                {"id": "nuxt", "name": "Nuxt 3", "command": "npx nuxi@latest init"},
                {"id": "next", "name": "Next.js", "command": "npx create-next-app@latest --typescript"}
            ]
        },
        {
            "id": "database",
            "name": "Database",
            "description": "Databases and data processing services",
            "icon": "database",
            "examples": ["MongoDB", "PostgreSQL", "Redis"],
            "creation_modes": ["config-only"],
            "scaffold_options": []
        },
        {
            "id": "workflow",
            "name": "Workflow",
            "description": "Workflow automation and integration tools",
            "icon": "workflow",
            "examples": ["n8n", "Airflow", "Custom Workers"],
            "creation_modes": ["config-only", "upload"],
            "scaffold_options": []
        }
    ]


# ============ TEMPLATE VALIDATION ============

@router.post("/custom/{template_id}/validate")
async def start_template_validation(
    template_id: str,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_active_user)
):
    """
    Start validation process for a custom template.
    
    This will create temporary test apps for each environment defined
    in the template (dev, staging, prod). The apps will be deployed
    and monitored. If all environments deploy successfully, the template
    status changes to 'ready'.
    
    Test apps are named: _test-{template_id}-{env}
    """
    db = get_db()
    
    template = await db.custom_templates.find_one({"id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    if template.get("status") == "validating":
        raise HTTPException(status_code=400, detail="Validation already in progress")
    
    if template.get("status") == "ready":
        raise HTTPException(status_code=400, detail="Template already validated. Use /re-validate to test again.")
    
    # Create test apps list
    test_apps = []
    for env in template.get("environments", ["dev", "prod"]):
        test_apps.append({
            "environment": env,
            "app_name": f"_test-{template_id}-{env}",
            "status": "pending",
            "error_message": None,
            "created_at": datetime.utcnow()
        })
    
    # Update template status
    await db.custom_templates.update_one(
        {"id": template_id},
        {"$set": {
            "status": "validating",
            "test_apps": test_apps,
            "validation_started_at": datetime.utcnow(),
            "validation_completed_at": None
        }}
    )
    
    # Start background task to create and monitor test apps
    background_tasks.add_task(
        _run_template_validation,
        template_id,
        template,
        test_apps
    )
    
    return {
        "message": f"Validation started for template '{template_id}'",
        "status": "validating",
        "test_apps": test_apps,
        "next_step": "Check /custom/{template_id}/validation-status for progress"
    }


async def _run_template_validation(template_id: str, template: dict, test_apps: list):
    """
    Background task to create test apps and monitor their deployment.
    """
    from app.routers.apps import create_app
    from app.models import AppCreate, ExposureConfig
    
    db = get_db()
    all_healthy = True
    
    for i, test_app in enumerate(test_apps):
        try:
            # Update status to deploying
            test_apps[i]["status"] = "deploying"
            await db.custom_templates.update_one(
                {"id": template_id},
                {"$set": {"test_apps": test_apps}}
            )
            
            # Create the test app using the apps router
            app_create = AppCreate(
                name=test_app["app_name"],
                template=template.get("base_template", "vue3-spa"),  # Use base or default
                description=f"Validation test for template {template_id}",
                environments=[test_app["environment"]],
                creation_mode="empty",  # Empty for quick test
                exposure=ExposureConfig(type="tailscale")  # Internal only
            )
            
            # Import and call the create function
            # Note: This is simplified - in production you'd call the service directly
            from app.services.pipeline_service import PipelineService
            pipeline_service = PipelineService()
            
            result = await pipeline_service.create_app(
                name=test_app["app_name"],
                template=template.get("base_template", "vue3-spa"),
                description=f"Test app for {template_id}",
                environments=[test_app["environment"]],
                exposure_type="tailscale"
            )
            
            if result.get("success"):
                test_apps[i]["status"] = "deployed"
                test_apps[i]["repo_url"] = result.get("repo_url")
            else:
                test_apps[i]["status"] = "failed"
                test_apps[i]["error_message"] = result.get("error", "Unknown error")
                all_healthy = False
                
        except Exception as e:
            logger.error(f"Error creating test app {test_app['app_name']}: {e}")
            test_apps[i]["status"] = "failed"
            test_apps[i]["error_message"] = str(e)
            all_healthy = False
        
        # Update DB after each app
        await db.custom_templates.update_one(
            {"id": template_id},
            {"$set": {"test_apps": test_apps}}
        )
    
    # Final status update
    final_status = "ready" if all_healthy else "validation_failed"
    await db.custom_templates.update_one(
        {"id": template_id},
        {"$set": {
            "status": final_status,
            "validation_completed_at": datetime.utcnow()
        }}
    )
    
    logger.info(f"Template '{template_id}' validation completed: {final_status}")


@router.get("/custom/{template_id}/validation-status")
async def get_validation_status(template_id: str):
    """
    Get the current validation status of a template.
    
    Returns:
    - status: draft, validating, validation_failed, ready
    - test_apps: Array of test apps with their individual statuses
    - progress: Percentage of apps deployed
    """
    db = get_db()
    
    template = await db.custom_templates.find_one({"id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    test_apps = template.get("test_apps", [])
    total = len(test_apps) if test_apps else 1
    completed = sum(1 for app in test_apps if app.get("status") in ["deployed", "healthy", "failed"])
    healthy = sum(1 for app in test_apps if app.get("status") in ["deployed", "healthy"])
    failed = sum(1 for app in test_apps if app.get("status") == "failed")
    
    return {
        "template_id": template_id,
        "status": template.get("status", "draft"),
        "test_apps": test_apps,
        "progress": {
            "total": total,
            "completed": completed,
            "healthy": healthy,
            "failed": failed,
            "percentage": int((completed / total) * 100) if total > 0 else 0
        },
        "validation_started_at": template.get("validation_started_at"),
        "validation_completed_at": template.get("validation_completed_at"),
        "can_publish": template.get("status") == "ready"
    }


@router.delete("/custom/{template_id}/test-apps")
async def delete_test_apps(
    template_id: str,
    current_user = Depends(get_current_active_user)
):
    """
    Delete all test apps for a template.
    
    Use this to clean up after a failed validation before retrying,
    or after approving a template to remove the test apps.
    """
    db = get_db()
    
    template = await db.custom_templates.find_one({"id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    test_apps = template.get("test_apps", [])
    deleted = []
    errors = []
    
    for test_app in test_apps:
        try:
            app_name = test_app.get("app_name")
            
            # Delete from apps collection
            await db.apps.delete_one({"name": app_name})
            
            # TODO: Also delete Bitbucket repo and ArgoCD app
            # For now just mark as deleted
            deleted.append(app_name)
            
        except Exception as e:
            errors.append({"app": test_app.get("app_name"), "error": str(e)})
    
    # Reset template status to draft if validation failed
    new_status = "draft" if template.get("status") == "validation_failed" else template.get("status")
    
    await db.custom_templates.update_one(
        {"id": template_id},
        {"$set": {
            "test_apps": [],
            "status": new_status
        }}
    )
    
    return {
        "message": f"Deleted {len(deleted)} test apps",
        "deleted": deleted,
        "errors": errors if errors else None,
        "template_status": new_status
    }


@router.post("/custom/{template_id}/approve")
async def approve_template(
    template_id: str,
    current_user = Depends(get_current_active_user)
):
    """
    Approve a validated template and make it available for production use.
    
    This will:
    1. Verify the template passed validation (status = ready)
    2. Delete all test apps
    3. Mark the template as published
    """
    db = get_db()
    
    template = await db.custom_templates.find_one({"id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    if template.get("status") != "ready":
        raise HTTPException(
            status_code=400, 
            detail=f"Template must be in 'ready' status to approve. Current: {template.get('status')}"
        )
    
    # Delete test apps first
    test_apps = template.get("test_apps", [])
    for test_app in test_apps:
        try:
            await db.apps.delete_one({"name": test_app.get("app_name")})
        except Exception as e:
            logger.warning(f"Failed to delete test app {test_app.get('app_name')}: {e}")
    
    # Approve and publish
    await db.custom_templates.update_one(
        {"id": template_id},
        {"$set": {
            "test_apps": [],
            "is_published": True,
            "published_at": datetime.utcnow(),
            "published_by": current_user.username,
            "approved_at": datetime.utcnow(),
            "approved_by": current_user.username
        }}
    )
    
    return {
        "message": f"🎉 Template '{template_id}' approved and published!",
        "status": "ready",
        "is_published": True,
        "test_apps_deleted": len(test_apps),
        "available_for": "All users can now create apps with this template"
    }


@router.post("/custom/{template_id}/re-validate")
async def re_validate_template(
    template_id: str,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_active_user)
):
    """
    Re-run validation on a template that's already validated or failed.
    
    Useful for:
    - Testing after making changes to template config
    - Verifying fixes after a failed validation
    """
    db = get_db()
    
    template = await db.custom_templates.find_one({"id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    if template.get("status") == "validating":
        raise HTTPException(status_code=400, detail="Validation already in progress")
    
    # Clean up any existing test apps first
    await delete_test_apps(template_id, current_user)
    
    # Reset to draft and start fresh validation
    await db.custom_templates.update_one(
        {"id": template_id},
        {"$set": {"status": "draft", "is_published": False}}
    )
    
    # Start validation
    return await start_template_validation(template_id, background_tasks, current_user)


# ============ PIPELINE ANALYZER ============

class AnalyzeRequest(BaseModel):
    """Request para analizar código y sugerir pipeline"""
    files: Dict[str, Optional[str]]  # filename -> content (or None for presence-only check)


@router.post("/analyze-pipeline")
async def analyze_pipeline(
    request: AnalyzeRequest,
    current_user = Depends(get_current_active_user)
):
    """
    Analyze project files and suggest optimal pipeline configuration.
    
    Send a dictionary of files where:
    - Key is the filename (e.g., "package.json", "requirements.txt")
    - Value is the file content (or null to just check presence)
    
    Returns detected framework, suggested pipeline YAML, and recommendations.
    """
    from app.services.pipeline_analyzer import pipeline_analyzer
    
    try:
        analysis = await pipeline_analyzer.analyze_repository(request.files)
        
        return {
            "detected_framework": analysis.detected_framework,
            "detected_language": analysis.detected_language,
            "confidence": analysis.confidence,
            "placeholders": analysis.placeholders,
            "warnings": analysis.warnings,
            "recommendations": analysis.recommendations,
            "suggested_pipeline": analysis.suggested_pipeline
        }
    except Exception as e:
        logger.error(f"Error analyzing pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-pipeline/{template_name}")
async def generate_pipeline(
    template_name: str,
    app_name: str,
    environments: List[str] = ["dev", "prod"],
    current_user = Depends(get_current_active_user)
):
    """
    Generate a complete pipeline YAML for the given template and app name.
    
    Args:
    - template_name: frontend-vite, backend-python, etc.
    - app_name: Name of the application
    - environments: Which environments to include (default: dev, prod)
    """
    from app.services.pipeline_analyzer import pipeline_analyzer
    
    try:
        pipeline_yaml = pipeline_analyzer.generate_pipeline(
            template_name=template_name,
            app_name=app_name,
            environments=environments
        )
        
        return {
            "template_name": template_name,
            "app_name": app_name,
            "environments": environments,
            "pipeline_yaml": pipeline_yaml
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ CATALOG V4: CATEGORIES ============

@router.get("/catalog/categories")
async def get_categories():
    """
    Get all template categories.
    
    Returns categories with:
    - id: Category identifier
    - name: Display name
    - icon: Emoji icon
    - description: Category description
    """
    try:
        categories = await template_service.get_categories_list()
        return {
            "categories": categories,
            "total": len(categories)
        }
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/categories/{category_id}")
async def get_category(category_id: str):
    """
    Get a specific category with its templates.
    """
    try:
        category = await template_service.get_category(category_id)
        if not category:
            raise HTTPException(status_code=404, detail=f"Category '{category_id}' not found")
        
        # Get templates for this category
        templates = await template_service.get_templates(category=category_id)
        
        return {
            **category,
            "id": category_id,
            "templates": templates,
            "template_count": len(templates)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting category {category_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ CATALOG V4: STACKS ============


@router.get("/catalog/stacks")
async def get_stacks(popular_only: bool = False):
    """
    Get all available stacks (predefined combinations of templates).
    
    Stacks are pre-configured bundles like:
    - fullstack-vue-fastapi: Frontend + API + Database
    - workflow-n8n: n8n + Postgres
    """
    try:
        stacks = await template_service.get_stacks(popular_only=popular_only)
        return {
            "stacks": stacks,
            "total": len(stacks)
        }
    except Exception as e:
        logger.error(f"Error getting stacks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/stacks/{stack_id}")
async def get_stack_details(stack_id: str):
    """
    Get detailed information about a specific stack.
    
    Returns:
    - Stack metadata
    - Components with their template details
    - Wiring configuration (how components connect)
    """
    try:
        stack = await template_service.get_stack_details(stack_id)
        if not stack:
            raise HTTPException(status_code=404, detail=f"Stack '{stack_id}' not found")
        return stack
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stack {stack_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# El despliegue de stacks vive en app/routers/stacks.py (POST /api/v1/stacks).
# El que había aquí insertaba documentos sueltos en Mongo con otro esquema y no
# llamaba al deployer: dejaba apps fantasma sin repositorio ni manifiestos.


# ============ CATALOG V4: EXPOSURE MODES ============

@router.get("/catalog/exposure-modes")
async def get_exposure_modes():
    """
    Get all available exposure modes.
    
    Exposure modes define how an app is accessible:
    - public: Internet-accessible via Traefik ingress
    - tailscale: VPN-only access via Tailscale
    - both: Mixed (some endpoints public, some private)
    - internal: Cluster-only, no external access
    """
    try:
        modes = await template_service.get_exposure_modes()
        return {
            "exposure_modes": modes,
            "default": "tailscale"
        }
    except Exception as e:
        logger.error(f"Error getting exposure modes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ CATALOG V4: CACHE STATUS ============

@router.get("/catalog/status")
async def get_catalog_status():
    """
    Get the status of the template catalog cache.
    """
    try:
        cache_status = template_service.get_cache_status()
        catalog = await template_service._get_catalog()
        
        return {
            **cache_status,
            "catalog_version": catalog.get("version", "unknown"),
            "template_count": len(catalog.get("templates", [])),
            "stack_count": len(catalog.get("stacks", [])),
            "category_count": len(catalog.get("categories", {}))
        }
    except Exception as e:
        logger.error(f"Error getting catalog status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


"""
AI Service - Análisis inteligente de apps y errores
====================================================
Soporta múltiples proveedores: DeepSeek, OpenAI, Anthropic
Configurable desde MongoDB (system_config)
"""

import httpx
from typing import Optional
from app.db import get_db


class AIService:
    def __init__(self):
        self._config = None
    
    async def _load_config(self):
        """Carga configuración de IA desde MongoDB"""
        if self._config:
            return self._config
            
        db = get_db()
        config = await db.system_config.find_one({"_id": "main"})
        
        if config and config.get("ai_api_key"):
            self._config = {
                "provider": config.get("ai_provider", "deepseek"),
                "api_key": config.get("ai_api_key"),
                "model": config.get("ai_model", "deepseek-chat"),
                "base_url": config.get("ai_base_url", "https://api.deepseek.com")
            }
        else:
            # Fallback defaults
            self._config = {
                "provider": "deepseek",
                "api_key": None,
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com"
            }
        
        return self._config
    
    async def analyze_pipeline_error(self, app_name: str, pipeline_logs: str, error_message: str, pipeline_info: dict = None) -> dict:
        """
        Analiza un error de pipeline y genera un resumen y recomendaciones.
        
        Args:
            app_name: Nombre de la app
            pipeline_logs: Logs concatenados (hasta 8000 chars)
            error_message: Mensaje de error específico
            pipeline_info: Info adicional del pipeline (branch, commit, etc)
        """
        config = await self._load_config()
        
        if not config.get("api_key"):
            return {
                "summary": "AI not configured",
                "details": error_message,
                "recommendations": ["Configure AI credentials in Settings"]
            }
        
        # Construir contexto más rico
        context_parts = [f'App: "{app_name}"']
        
        if pipeline_info:
            context_parts.append(f"Branch: {pipeline_info.get('branch', 'N/A')}")
            context_parts.append(f"Commit: {pipeline_info.get('commit', 'N/A')}")
            context_parts.append(f"Build #: {pipeline_info.get('build_number', 'N/A')}")
            context_parts.append(f"Trigger: {pipeline_info.get('trigger', 'N/A')}")
        
        pipeline_context = "\n".join(context_parts)
        
        # Usar más caracteres de logs (hasta 6000) para mejor análisis
        truncated_logs = pipeline_logs[:6000] if len(pipeline_logs) > 6000 else pipeline_logs
        
        prompt = f"""Analiza este error de CI/CD pipeline.

{pipeline_context}

Error reportado:
{error_message}

Logs del pipeline:
{truncated_logs}

Responde en JSON con este formato exacto:
{{
    "summary": "Una línea describiendo el problema principal",
    "cause": "Causa raíz identificada",
    "recommendations": ["Paso 1 para solucionar", "Paso 2 si aplica", "Paso 3 si aplica"],
    "severity": "low|medium|high|critical",
    "affected_files": ["archivo1.py", "archivo2.js"] // si se puede identificar
}}"""

        return await self._call_ai(prompt, json_mode=True)
    
    async def get_app_status_summary(self, app_data: dict, pipeline_status: dict) -> str:
        """
        Genera un resumen rápido del estado de una app
        """
        config = await self._load_config()
        
        if not config.get("api_key"):
            return self._generate_basic_summary(app_data, pipeline_status)
        
        prompt = f"""Resume el estado de esta app en 1-2 oraciones cortas para un dashboard.

App: {app_data.get('name')}
Status DB: {app_data.get('status')}
Pipeline: {pipeline_status.get('state', 'unknown')} - {pipeline_status.get('result', 'N/A')}
Último error: {app_data.get('error', 'None')}
Environments: {app_data.get('environments', ['prod'])}

Responde solo con el resumen, sin formato adicional."""

        result = await self._call_ai(prompt, json_mode=False)
        return result if isinstance(result, str) else result.get("response", "Status unknown")
    
    def _generate_basic_summary(self, app_data: dict, pipeline_status: dict) -> str:
        """Genera resumen básico sin IA"""
        status = app_data.get('status', 'unknown')
        p_state = pipeline_status.get('state', 'unknown')
        p_result = pipeline_status.get('result', '')
        
        if status == 'running' and p_result == 'SUCCESSFUL':
            return "✅ App running, last deployment successful"
        elif status == 'running' and p_state == 'IN_PROGRESS':
            return "🔄 App running, new deployment in progress"
        elif status == 'error' or p_result == 'FAILED':
            return f"❌ Deployment failed: {app_data.get('error', 'Check pipeline logs')[:50]}"
        elif p_state == 'PENDING':
            return "⏳ Pipeline pending execution"
        else:
            return f"Status: {status}, Pipeline: {p_state}"
    
    async def _call_ai(self, prompt: str, json_mode: bool = False) -> dict | str:
        """Llama a la API de IA configurada"""
        config = await self._load_config()
        
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json"
        }
        
        body = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": "Eres un experto en DevOps y CI/CD. Responde de forma concisa y técnica."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 500
        }
        
        if json_mode and config["provider"] in ["deepseek", "openai"]:
            body["response_format"] = {"type": "json_object"}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{config['base_url']}/v1/chat/completions",
                    headers=headers,
                    json=body
                )
                
                if response.status_code != 200:
                    return {"error": f"AI API error: {response.status_code}"}
                
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                if json_mode:
                    import json
                    try:
                        return json.loads(content)
                    except:
                        return {"response": content}
                
                return content
                
        except Exception as e:
            return {"error": str(e)} if json_mode else f"AI error: {str(e)}"


# Singleton instance
ai_service = AIService()

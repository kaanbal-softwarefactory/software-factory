"""
Pipeline Analyzer Service

Analyzes project code to suggest optimal pipeline configuration.
Uses file detection rules to identify frameworks and generate
appropriate Bitbucket Pipeline YAML.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)


@dataclass
class PipelineAnalysis:
    """Result of pipeline analysis"""
    detected_framework: str
    detected_language: str
    suggested_pipeline: str
    placeholders: Dict[str, str]
    confidence: float  # 0-1
    warnings: List[str]
    recommendations: List[str]


class PipelineAnalyzerService:
    """
    Analyzes project structure and suggests pipeline configuration.
    """
    
    # Detection rules for frameworks
    DETECTION_RULES = {
        # Frontend frameworks
        "vue": {
            "files": ["vite.config.ts", "vite.config.js", "vue.config.js"],
            "package_deps": ["vue", "@vue/cli"],
            "language": "javascript",
            "category": "frontend",
            "pipeline_template": "frontend-vite",
            "placeholders": {
                "NODE_VERSION": "20",
                "BUILD_COMMAND": "npm run build",
                "BUILD_OUTPUT": "dist",
                "INSTALL_COMMAND": "npm ci"
            }
        },
        "react": {
            "files": ["vite.config.ts", "vite.config.js"],
            "package_deps": ["react", "react-dom"],
            "language": "javascript",
            "category": "frontend",
            "pipeline_template": "frontend-vite",
            "placeholders": {
                "NODE_VERSION": "20",
                "BUILD_COMMAND": "npm run build",
                "BUILD_OUTPUT": "dist",
                "INSTALL_COMMAND": "npm ci"
            }
        },
        "next": {
            "files": ["next.config.js", "next.config.mjs", "next.config.ts"],
            "package_deps": ["next"],
            "language": "javascript",
            "category": "fullstack",
            "pipeline_template": "frontend-next",
            "placeholders": {
                "NODE_VERSION": "20",
                "BUILD_COMMAND": "npm run build",
                "BUILD_OUTPUT": ".next",
                "INSTALL_COMMAND": "npm ci"
            }
        },
        "nuxt": {
            "files": ["nuxt.config.ts", "nuxt.config.js"],
            "package_deps": ["nuxt"],
            "language": "javascript",
            "category": "fullstack",
            "pipeline_template": "frontend-nuxt",
            "placeholders": {
                "NODE_VERSION": "20",
                "BUILD_COMMAND": "npm run build",
                "BUILD_OUTPUT": ".output",
                "INSTALL_COMMAND": "npm ci"
            }
        },
        # Backend frameworks
        "fastapi": {
            "files": ["requirements.txt", "pyproject.toml"],
            "file_contents": {"requirements.txt": "fastapi", "main.py": "FastAPI"},
            "language": "python",
            "category": "backend",
            "pipeline_template": "backend-python",
            "placeholders": {
                "PYTHON_VERSION": "3.11",
                "INSTALL_COMMAND": "pip install -r requirements.txt",
                "RUN_COMMAND": "uvicorn main:app --host 0.0.0.0 --port 8000",
                "PORT": "8000"
            }
        },
        "flask": {
            "files": ["requirements.txt", "app.py"],
            "file_contents": {"requirements.txt": "flask"},
            "language": "python",
            "category": "backend",
            "pipeline_template": "backend-python",
            "placeholders": {
                "PYTHON_VERSION": "3.11",
                "INSTALL_COMMAND": "pip install -r requirements.txt",
                "RUN_COMMAND": "gunicorn app:app --bind 0.0.0.0:8000",
                "PORT": "8000"
            }
        },
        "express": {
            "files": ["package.json"],
            "package_deps": ["express"],
            "language": "javascript",
            "category": "backend",
            "pipeline_template": "backend-node",
            "placeholders": {
                "NODE_VERSION": "20",
                "INSTALL_COMMAND": "npm ci",
                "RUN_COMMAND": "node index.js",
                "PORT": "3000"
            }
        },
        "nestjs": {
            "files": ["nest-cli.json"],
            "package_deps": ["@nestjs/core"],
            "language": "javascript",
            "category": "backend",
            "pipeline_template": "backend-node",
            "placeholders": {
                "NODE_VERSION": "20",
                "BUILD_COMMAND": "npm run build",
                "INSTALL_COMMAND": "npm ci",
                "RUN_COMMAND": "node dist/main.js",
                "PORT": "3000"
            }
        }
    }
    
    # Pipeline templates
    PIPELINE_TEMPLATES = {
        "frontend-vite": """
image: node:{{NODE_VERSION}}-alpine

definitions:
  caches:
    npm: $HOME/.npm
  steps:
    - step: &build
        name: 📦 Install & Build
        caches:
          - npm
        script:
          - {{INSTALL_COMMAND}}
          - {{BUILD_COMMAND}}
        artifacts:
          - {{BUILD_OUTPUT}}/**

    - step: &docker-build
        name: 🐳 Build & Push Docker
        services:
          - docker
        script:
          - export IMAGE_TAG="${BITBUCKET_COMMIT:0:7}"
          - docker build -t $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG .
          - docker build -t $DOCKERHUB_USERNAME/{{APP_NAME}}:latest .
          - echo $DOCKERHUB_PASSWORD | docker login -u $DOCKERHUB_USERNAME --password-stdin
          - docker push $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG
          - docker push $DOCKERHUB_USERNAME/{{APP_NAME}}:latest

    - step: &update-infra
        name: 🚀 Update Infra
        script:
          - apk add --no-cache git
          - export IMAGE_TAG="${BITBUCKET_COMMIT:0:7}"
          - git clone https://$INFRA_REPO_AUTH@bitbucket.org/$BITBUCKET_WORKSPACE/infra-gitops.git
          - cd infra-gitops/apps/{{APP_NAME}}/overlays/{{ENV}}
          - sed -i "s|image:.*|image: $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG|" kustomization.yaml
          - git config user.email "pipeline@${DOMAIN:-kaanbal.local}"
          - git config user.name "Kaanbal Engine"
          - git add .
          - git commit -m "deploy({{APP_NAME}}): $IMAGE_TAG to {{ENV}}"
          - git push

pipelines:
  branches:
    main:
      - step: *build
      - step:
          <<: *docker-build
          deployment: production
      - step:
          <<: *update-infra
          script:
            - export ENV=prod
            - *update-infra
    
    develop:
      - step: *build
      - step:
          <<: *docker-build
          name: 🐳 Build & Push Docker (DEV)
      - step:
          <<: *update-infra
          name: 🚀 Update Infra (DEV)
          script:
            - export ENV=dev
""",
        
        "backend-python": """
image: python:{{PYTHON_VERSION}}-slim

definitions:
  caches:
    pip: $HOME/.cache/pip
  steps:
    - step: &test
        name: 🧪 Lint & Test
        caches:
          - pip
        script:
          - {{INSTALL_COMMAND}}
          - pip install pytest ruff
          - ruff check . || true
          - pytest tests/ || true

    - step: &docker-build
        name: 🐳 Build & Push Docker
        services:
          - docker
        script:
          - export IMAGE_TAG="${BITBUCKET_COMMIT:0:7}"
          - docker build -t $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG .
          - docker build -t $DOCKERHUB_USERNAME/{{APP_NAME}}:latest .
          - echo $DOCKERHUB_PASSWORD | docker login -u $DOCKERHUB_USERNAME --password-stdin
          - docker push $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG
          - docker push $DOCKERHUB_USERNAME/{{APP_NAME}}:latest

    - step: &update-infra
        name: 🚀 Update Infra
        image: alpine:latest
        script:
          - apk add --no-cache git
          - export IMAGE_TAG="${BITBUCKET_COMMIT:0:7}"
          - git clone https://$INFRA_REPO_AUTH@bitbucket.org/$BITBUCKET_WORKSPACE/infra-gitops.git
          - cd infra-gitops/apps/{{APP_NAME}}/overlays/{{ENV}}
          - sed -i "s|image:.*|image: $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG|" kustomization.yaml
          - git config user.email "pipeline@${DOMAIN:-kaanbal.local}"
          - git config user.name "Kaanbal Engine"
          - git add .
          - git commit -m "deploy({{APP_NAME}}): $IMAGE_TAG to {{ENV}}"
          - git push

pipelines:
  branches:
    main:
      - step: *test
      - step:
          <<: *docker-build
          deployment: production
      - step:
          <<: *update-infra
          script:
            - export ENV=prod
    
    develop:
      - step: *test
      - step:
          <<: *docker-build
          name: 🐳 Build & Push Docker (DEV)
      - step:
          <<: *update-infra
          name: 🚀 Update Infra (DEV)
          script:
            - export ENV=dev
""",

        "backend-node": """
image: node:{{NODE_VERSION}}-alpine

definitions:
  caches:
    npm: $HOME/.npm
  steps:
    - step: &test
        name: 🧪 Lint & Test
        caches:
          - npm
        script:
          - {{INSTALL_COMMAND}}
          - npm run lint || true
          - npm test || true

    - step: &docker-build
        name: 🐳 Build & Push Docker
        services:
          - docker
        script:
          - export IMAGE_TAG="${BITBUCKET_COMMIT:0:7}"
          - docker build -t $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG .
          - docker build -t $DOCKERHUB_USERNAME/{{APP_NAME}}:latest .
          - echo $DOCKERHUB_PASSWORD | docker login -u $DOCKERHUB_USERNAME --password-stdin
          - docker push $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG
          - docker push $DOCKERHUB_USERNAME/{{APP_NAME}}:latest

    - step: &update-infra
        name: 🚀 Update Infra
        image: alpine:latest
        script:
          - apk add --no-cache git
          - export IMAGE_TAG="${BITBUCKET_COMMIT:0:7}"
          - git clone https://$INFRA_REPO_AUTH@bitbucket.org/$BITBUCKET_WORKSPACE/infra-gitops.git
          - cd infra-gitops/apps/{{APP_NAME}}/overlays/{{ENV}}
          - sed -i "s|image:.*|image: $DOCKERHUB_USERNAME/{{APP_NAME}}:$IMAGE_TAG|" kustomization.yaml
          - git config user.email "pipeline@${DOMAIN:-kaanbal.local}"
          - git config user.name "Kaanbal Engine"
          - git add .
          - git commit -m "deploy({{APP_NAME}}): $IMAGE_TAG to {{ENV}}"
          - git push

pipelines:
  branches:
    main:
      - step: *test
      - step:
          <<: *docker-build
          deployment: production
      - step:
          <<: *update-infra
          script:
            - export ENV=prod
    
    develop:
      - step: *test
      - step:
          <<: *docker-build
          name: 🐳 Build & Push Docker (DEV)
      - step:
          <<: *update-infra
          name: 🚀 Update Infra (DEV)
          script:
            - export ENV=dev
"""
    }

    def __init__(self):
        pass

    async def analyze_repository(self, files: Dict[str, str]) -> PipelineAnalysis:
        """
        Analyze repository files and suggest pipeline configuration.
        
        Args:
            files: Dict of filename -> content (or None for just presence check)
            
        Returns:
            PipelineAnalysis with detected framework and suggested pipeline
        """
        detected = None
        confidence = 0.0
        warnings = []
        recommendations = []
        
        file_names = list(files.keys())
        
        # Check each framework's detection rules
        for framework, rules in self.DETECTION_RULES.items():
            score = 0
            max_score = 0
            
            # Check for required files
            if "files" in rules:
                max_score += 2
                for f in rules["files"]:
                    if any(fn.endswith(f) or fn == f for fn in file_names):
                        score += 2
                        break
            
            # Check package.json dependencies
            if "package_deps" in rules and "package.json" in files and files["package.json"]:
                max_score += 3
                pkg_content = files["package.json"]
                for dep in rules["package_deps"]:
                    if f'"{dep}"' in pkg_content:
                        score += 3
                        break
            
            # Check file contents
            if "file_contents" in rules:
                for filename, search_str in rules["file_contents"].items():
                    max_score += 2
                    if filename in files and files[filename] and search_str in files[filename]:
                        score += 2
            
            # Calculate confidence
            if max_score > 0:
                fw_confidence = score / max_score
                if fw_confidence > confidence:
                    confidence = fw_confidence
                    detected = framework
        
        if not detected:
            # Fallback: try to detect by file extensions
            if any(f.endswith(".py") for f in file_names):
                detected = "fastapi"  # Default Python to FastAPI
                confidence = 0.3
                warnings.append("Could not detect specific Python framework, defaulting to FastAPI")
            elif any(f.endswith((".js", ".ts")) for f in file_names):
                detected = "express"  # Default JS to Express
                confidence = 0.3
                warnings.append("Could not detect specific JS framework, defaulting to Express")
            else:
                return PipelineAnalysis(
                    detected_framework="unknown",
                    detected_language="unknown",
                    suggested_pipeline="",
                    placeholders={},
                    confidence=0,
                    warnings=["Could not detect project type"],
                    recommendations=["Please specify the framework manually"]
                )
        
        rules = self.DETECTION_RULES[detected]
        template_name = rules["pipeline_template"]
        placeholders = rules["placeholders"].copy()
        
        # Get pipeline template
        suggested_pipeline = self.PIPELINE_TEMPLATES.get(template_name, "")
        
        # Add recommendations
        if confidence < 0.7:
            recommendations.append("Review the detected configuration as confidence is low")
        
        if rules["category"] == "backend":
            recommendations.append("Remember to configure DATABASE_URL secret")
        
        if rules["category"] == "frontend":
            recommendations.append("Ensure your build output folder matches the pipeline config")
        
        return PipelineAnalysis(
            detected_framework=detected,
            detected_language=rules["language"],
            suggested_pipeline=suggested_pipeline,
            placeholders=placeholders,
            confidence=confidence,
            warnings=warnings,
            recommendations=recommendations
        )
    
    def generate_pipeline(
        self, 
        template_name: str, 
        app_name: str,
        environments: List[str] = None,
        custom_placeholders: Dict[str, str] = None
    ) -> str:
        """
        Generate a complete pipeline YAML from template.
        
        Args:
            template_name: Name of the pipeline template
            app_name: Application name
            environments: List of environments to deploy to
            custom_placeholders: Override default placeholders
            
        Returns:
            Complete bitbucket-pipelines.yml content
        """
        if template_name not in self.PIPELINE_TEMPLATES:
            raise ValueError(f"Unknown pipeline template: {template_name}")
        
        template = self.PIPELINE_TEMPLATES[template_name]
        
        # Get default placeholders for this template
        for framework, rules in self.DETECTION_RULES.items():
            if rules["pipeline_template"] == template_name:
                placeholders = rules["placeholders"].copy()
                break
        else:
            placeholders = {}
        
        # Override with custom placeholders
        if custom_placeholders:
            placeholders.update(custom_placeholders)
        
        # Add app name
        placeholders["APP_NAME"] = app_name
        
        # Replace all placeholders
        result = template
        for key, value in placeholders.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        
        # Handle environments
        if environments:
            # TODO: Filter pipeline branches based on environments
            pass
        
        return result.strip()

    def get_dockerfile_template(self, framework: str) -> str:
        """Get a Dockerfile template for the detected framework."""
        
        dockerfiles = {
            "vue": """
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
            "react": """
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
            "fastapi": """
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
            "express": """
FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

EXPOSE 3000

CMD ["node", "index.js"]
"""
        }
        
        return dockerfiles.get(framework, dockerfiles["fastapi"]).strip()


# Singleton instance
pipeline_analyzer = PipelineAnalyzerService()

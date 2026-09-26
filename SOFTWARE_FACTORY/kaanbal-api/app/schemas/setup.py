from pydantic import BaseModel
from typing import List, Optional

class SetupRequest(BaseModel):
    git_username: str
    git_token: str
    dockerhub_username: Optional[str] = None
    dockerhub_token: Optional[str] = None
    modules: List[str] = []  # e.g. ["n8n", "emqx", "mongodb"]

class SetupResponse(BaseModel):
    status: str
    message: str
    steps_completed: List[str]
    missing_steps: List[str]

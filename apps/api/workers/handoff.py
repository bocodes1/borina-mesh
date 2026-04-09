from pydantic import BaseModel, Field
from typing import Optional

class HandoffPayload(BaseModel):
    repo_path: str = Field(..., description="Absolute path to the source repo")
    base_branch: str = Field("main", description="Branch to fork the worktree from")
    prompt: str = Field(..., description="Task description for the headless worker")
    cwd_snapshot: Optional[str] = Field(None, description="git status --porcelain output")
    diff_snapshot: Optional[str] = Field(None, description="git diff of unstaged changes")
    recent_files: list[str] = Field(default_factory=list)
    conversation_tail: Optional[str] = Field(None, description="Last ~20 messages")

class HandoffResponse(BaseModel):
    job_id: int
    dashboard_url: str
    worktree_path: str

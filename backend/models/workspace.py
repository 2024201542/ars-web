"""工作区数据模型"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class FileInfo(BaseModel):
    id: str
    filename: str
    stored_path: str
    mime_type: Optional[str] = None
    size_bytes: int = 0
    adapter: Optional[str] = None
    columns: Optional[list[str]] = None
    ingested_at: str = ""


class VenvCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    language: Literal["python", "r"] = "python"
    packages: list[str] = Field(default_factory=list, max_length=50)


class VenvInfo(BaseModel):
    name: str
    language: str
    python_version: Optional[str] = None
    packages: list[str] = []
    created_at: str = ""


class ExecuteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=10000)
    language: Literal["python", "r"] = "python"
    venv: str = "default"


class ExecuteResult(BaseModel):
    id: str
    language: str
    venv: str
    status: Literal["pending", "running", "completed", "error"]
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    output_files: list[str] = []
    started_at: str = ""
    finished_at: Optional[str] = None

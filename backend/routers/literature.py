"""查文献入口。知网仍是预留；查找文件只保存公开 PDF。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.literature_search import save_open_pdfs, search_literature as run_literature_search
from services.user_manager import get_user_id

router = APIRouter(prefix="/api/literature", tags=["literature"])


class LiteratureSearchRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    source: str = Field("cnki", max_length=40)


class LiteratureSaveRequest(BaseModel):
    dois: list[str] = Field(default_factory=list, max_length=8)


@router.post("/search")
async def search_literature(req: LiteratureSearchRequest, user_id: str = Depends(get_user_id)):
    return await run_literature_search(req.query, req.source)


@router.post("/save")
async def save_literature_files(req: LiteratureSaveRequest, user_id: str = Depends(get_user_id)):
    return await save_open_pdfs(user_id, req.dois)

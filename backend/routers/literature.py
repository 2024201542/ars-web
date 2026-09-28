"""查文献入口。当前只保留接口，不编造检索结果。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.literature_search import search_literature
from services.user_manager import get_user_id

router = APIRouter(prefix="/api/literature", tags=["literature"])


class LiteratureSearchRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    source: str = Field("cnki", max_length=40)


@router.post("/search")
async def search_literature(req: LiteratureSearchRequest, user_id: str = Depends(get_user_id)):
    return await search_literature(req.query, req.source)

"""工作区 API — 会话级文件管理"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Depends
from fastapi.responses import FileResponse
from services.workspace_manager import workspace_manager, session_dir
from services.user_manager import get_user_id
from services.state_tracker import tracker as state_tracker

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

async def _verify_session(session_id: str, user_id: str):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.get("/files")
async def list_files(session_id: str = Query(...), user_id: str = Depends(get_user_id)):
    await _verify_session(session_id, user_id)
    # 按用户工作区列出文件（非按会话）
    return {"data": await workspace_manager.list_user_files(user_id)}


@router.post("/files")
async def upload_file(session_id: str = Query(...), file: UploadFile = File(...), user_id: str = Depends(get_user_id)):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    try:
        return await workspace_manager.save_user_file(user_id, file.filename, await file.read(), file.content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/files/content")
async def file_content(session_id: str = Query(...), path: str = Query(...), user_id: str = Depends(get_user_id)):
    await _verify_session(session_id, user_id)
    content = await workspace_manager.get_content(session_id, path)
    if content is None:
        raise HTTPException(status_code=406, detail="无法预览此文件类型")
    return {"content": content, "path": path}


@router.get("/files/preview")
async def preview_file(session_id: str = Query(...), path: str = Query(...), user_id: str = Depends(get_user_id)):
    """DOCX/XLSX → HTML 转换预览。"""
    await _verify_session(session_id, user_id)
    fp = await workspace_manager.get_user_file_path(user_id, path)
    if not fp:
        raise HTTPException(status_code=404, detail="文件不存在")
    ext = fp.suffix.lower()

    if ext == ".docx":
        try:
            import mammoth
            with open(fp, "rb") as f:
                result = mammoth.convert_to_html(f)
            return {"type": "html", "content": result.value}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DOCX 转换失败: {e}")

    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(fp, read_only=True, data_only=True)
            parts = []
            for name in wb.sheetnames[:5]:
                ws = wb[name]
                rows = list(ws.iter_rows(values_only=True))[:1001]
                if not rows: continue
                nc = max(len(r) for r in rows)
                h = '<h4 class="text-xs font-ui text-ruc-text-dim mt-3 mb-1">' + name + '</h4><table>'
                h += '<thead><tr>' + ''.join(f'<th>{c or ""}</th>' for c in rows[0]) + '</tr></thead><tbody>'
                for row in rows[1:]:
                    cells = list(row) + [''] * (nc - len(row))
                    h += '<tr>' + ''.join(f'<td>{c or ""}</td>' for c in cells[:nc]) + '</tr>'
                h += '</tbody></table>'
                parts.append(h)
            wb.close()
            return {"type": "html", "content": ''.join(parts)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Excel 转换失败: {e}")

    raise HTTPException(status_code=406, detail=f"不支持预览: {ext}")


@router.get("/files/download")
async def download_file(session_id: str = Query(...), path: str = Query(...), user_id: str = Depends(get_user_id)):
    await _verify_session(session_id, user_id)
    fp = await workspace_manager.get_user_file_path(user_id, path)
    if not fp:
        raise HTTPException(status_code=404)
    return FileResponse(path=str(fp), filename=fp.name)


@router.delete("/files")
async def delete_file(session_id: str = Query(...), path: str = Query(...), user_id: str = Depends(get_user_id)):
    await _verify_session(session_id, user_id)
    await workspace_manager.delete_user_file(user_id, path)
    return {"ok": True}


@router.get("/search")
async def search_files(session_id: str = Query(...), q: str = Query(""), user_id: str = Depends(get_user_id)):
    """搜索工作区文件（@ 引用用）。"""
    await _verify_session(session_id, user_id)
    files = await workspace_manager.list_user_files(user_id)
    if not q:
        return {"data": files[:20]}
    ql = q.lower()
    matched = [f for f in files if ql in f.get("name", "").lower() or ql in f.get("dir", "").lower()]
    return {"data": matched[:20]}


@router.post("/refresh")
async def refresh_workspace(session_id: str = Query(...), user_id: str = Depends(get_user_id)):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404)
    return {"data": await workspace_manager.refresh(session_id)}

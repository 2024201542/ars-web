"""查文献。知网只留接口；开放检索先问 OpenAlex。

关键词检索被限流时，用 Crossref 定位 DOI，再向 OpenAlex 读取同一条记录。
查找文件只下载 OpenAlex 给出的公开 PDF，缺的字段留空，不编造。
"""

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

OPENALEX_WORKS = "https://api.openalex.org/works"
CROSSREF_WORKS = "https://api.crossref.org/works"
OPENALEX_PAGE = 8
_HEADERS = {"User-Agent": "ars-web/literature"}


def reserved_literature(query: str, source: str = "cnki") -> dict:
    text = (query or "").strip()
    origin = (source or "cnki").strip() or "cnki"
    return {
        "status": "reserved",
        "provider": origin,
        "query": text,
        "items": [],
        "message": "知网检索还没有接通，这次不会编造文献。",
    }


def work_from_openalex(item: dict) -> dict:
    authors = []
    for ship in item.get("authorships") or []:
        if not isinstance(ship, dict):
            continue
        name = ((ship.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    location = item.get("primary_location") or {}
    source = ""
    if isinstance(location, dict):
        venue = location.get("source") or {}
        if isinstance(venue, dict):
            source = (venue.get("display_name") or "").strip()
    doi = (item.get("doi") or "").strip()
    prefix = "https://doi.org/"
    if doi.lower().startswith(prefix):
        doi = doi[len(prefix):]
    year = item.get("publication_year")
    title = item.get("display_name") or item.get("title") or ""
    if not isinstance(title, str):
        title = ""
    return {
        "title": title.strip(),
        "authors": authors,
        "year": str(year) if isinstance(year, int) else "",
        "source": source,
        "doi": doi,
        "pdf_url": open_pdf_url(item),
    }


def works_from_openalex(payload: dict) -> list[dict]:
    rows = []
    for item in payload.get("results") or []:
        if isinstance(item, dict):
            rows.append(work_from_openalex(item))
    return rows


def work_from_crossref(item: dict) -> dict:
    titles = item.get("title") or []
    title = titles[0].strip() if titles and isinstance(titles[0], str) else ""
    authors = []
    for person in item.get("author") or []:
        if not isinstance(person, dict):
            continue
        given = (person.get("given") or "").strip()
        family = (person.get("family") or "").strip()
        name = " ".join(part for part in (given, family) if part)
        if not name:
            name = (person.get("name") or "").strip()
        if name:
            authors.append(name)
    year = ""
    issued = item.get("issued") if isinstance(item.get("issued"), dict) else {}
    parts = issued.get("date-parts") or []
    if parts and isinstance(parts[0], list) and parts[0] and isinstance(parts[0][0], int):
        year = str(parts[0][0])
    containers = item.get("container-title") or []
    venue = containers[0].strip() if containers and isinstance(containers[0], str) else ""
    doi = item.get("DOI") or ""
    if not isinstance(doi, str):
        doi = ""
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "source": venue,
        "doi": doi.strip(),
    }


def open_pdf_url(item: dict) -> str:
    """只认开放获取位置上的 pdf_url。落地页和 http 地址不算全文。"""
    if not isinstance(item, dict):
        return ""
    candidates = []
    best = item.get("best_oa_location")
    if isinstance(best, dict):
        candidates.append(best.get("pdf_url"))
    primary = item.get("primary_location")
    if isinstance(primary, dict) and primary.get("is_oa"):
        candidates.append(primary.get("pdf_url"))
    for loc in item.get("locations") or []:
        if isinstance(loc, dict) and loc.get("is_oa"):
            candidates.append(loc.get("pdf_url"))
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        url = raw.strip()
        if url.lower().startswith("https://"):
            return url
    return ""


def format_works(query: str, items: list[dict], heading: str = "OpenAlex 检索", show_files: bool = False) -> str:
    text = (query or "").strip()
    if not items:
        return f"OpenAlex 没有返回「{text}」的记录。没有编造文献。"
    lines = [f"{heading}：{text}", ""]
    for index, item in enumerate(items, 1):
        authors = "、".join(item.get("authors") or [])
        lines.extend([
            f"{index}. {item.get('title') or ''}",
            f"作者：{authors}",
            f"年份：{item.get('year') or ''}",
            f"来源：{item.get('source') or ''}",
            f"DOI：{item.get('doi') or ''}",
        ])
        if show_files:
            lines.append(f"全文：{'有公开 PDF' if item.get('pdf_url') else ''}")
        lines.append("")
    if show_files:
        lines.append("勾选有公开 PDF 的记录，可以放到左侧文件夹。没有公开全文的不会下载。")
    else:
        lines.append("以上是接口返回的记录。缺的字段留空，没有补写。")
    return "\n".join(lines).strip()


def _ok(query: str, items: list[dict], heading: str, show_files: bool = False) -> dict:
    return {
        "status": "ok",
        "provider": "openalex",
        "query": query,
        "items": items,
        "message": format_works(query, items, heading, show_files),
    }


def _error(query: str, note: str) -> dict:
    return {"status": "error", "provider": "openalex", "query": query, "items": [], "message": note}


async def _read_openalex_doi(client: httpx.AsyncClient, doi: str) -> dict | None:
    clean = (doi or "").strip()
    if not clean:
        return None
    response = await client.get(f"{OPENALEX_WORKS}/doi:{clean}", headers=_HEADERS)
    if response.status_code != 200:
        return None
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    row = work_from_openalex(payload)
    if not row["title"] and not row["doi"]:
        return None
    return row


async def _locate_then_read(client: httpx.AsyncClient, query: str, show_files: bool = False) -> dict:
    response = await client.get(
        CROSSREF_WORKS,
        params={"query": query, "rows": OPENALEX_PAGE},
        headers=_HEADERS,
    )
    response.raise_for_status()
    payload = response.json()
    message = payload.get("message") if isinstance(payload, dict) else {}
    located = []
    for item in (message or {}).get("items") or []:
        if isinstance(item, dict):
            located.append(work_from_crossref(item))
    rows = []
    for item in located:
        opened = await _read_openalex_doi(client, item.get("doi") or "")
        rows.append(opened or item)
        if len(rows) >= OPENALEX_PAGE:
            break
    heading = "OpenAlex 记录（关键词检索太频繁，先用 Crossref 定位 DOI，再向 OpenAlex 读取）"
    return _ok(query, rows, heading, show_files)


async def search_openalex(query: str, with_files: bool = False) -> dict:
    text = (query or "").strip()
    if not text:
        return {
            "status": "empty",
            "provider": "openalex",
            "query": "",
            "items": [],
            "message": "先写下检索词。",
        }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            response = await client.get(
                OPENALEX_WORKS,
                params={"search": text, "per_page": OPENALEX_PAGE},
                headers=_HEADERS,
            )
            if response.status_code == 429:
                try:
                    return await _locate_then_read(client, text, with_files)
                except (httpx.HTTPError, ValueError):
                    return _error(text, "OpenAlex 这次检索太频繁，改走 Crossref 也没有连上。没有编造文献。")
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        return _error(text, f"OpenAlex 这次没有连上（{exc.response.status_code}）。没有编造文献。")
    except (httpx.HTTPError, ValueError) as exc:
        return _error(text, f"OpenAlex 这次没有连上（{type(exc).__name__}）。没有编造文献。")
    items = works_from_openalex(payload if isinstance(payload, dict) else {})
    return _ok(text, items, "OpenAlex 检索", with_files)


def clean_doi(raw: str) -> str:
    text = (raw or "").strip()
    prefix = "https://doi.org/"
    if text.lower().startswith(prefix):
        text = text[len(prefix):]
    if not text.startswith("10.") or len(text) > 200 or any(ch in text for ch in " \t\r\n<>\"'#"):
        raise ValueError("没有这条 DOI")
    return text


def assert_public_https(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        raise ValueError("不是公开的 PDF 地址")
    if host in {"localhost"} or host.endswith(".local") or host.endswith(".localhost"):
        raise ValueError("不是公开的 PDF 地址")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url.strip()
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        raise ValueError("不是公开的 PDF 地址")
    return url.strip()


# 本机代理常用的假 IP。域名本身仍须是 https 主机名，字面量内网地址继续拒绝。
_PROXY_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")


def _reject_ip(raw: str) -> None:
    ip = ipaddress.ip_address(raw)
    if isinstance(ip, ipaddress.IPv4Address) and ip in _PROXY_FAKE_IP:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        raise ValueError("不是公开的 PDF 地址")


async def assert_public_host(hostname: str) -> None:
    host = (hostname or "").lower().rstrip(".")
    assert_public_https(f"https://{host}/paper.pdf")
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("下载没有连上") from exc
    if not infos:
        raise ValueError("下载没有连上")
    for info in infos:
        _reject_ip(info[4][0])


def ensure_pdf(data: bytes, limit: int) -> bytes:
    if len(data) > limit:
        raise ValueError("文件过大")
    if not data.startswith(b"%PDF"):
        raise ValueError("返回的不是 PDF")
    return data


def pdf_filename(title: str, doi: str) -> str:
    raw = (title or "").strip() or (doi or "paper").replace("/", "_")
    raw = raw.replace("/", " ").replace("\\", " ")
    raw = "_".join(raw.split())
    raw = raw[:70].strip("._") or "paper"
    return f"{raw}.pdf"


async def _download_pdf(client: httpx.AsyncClient, url: str, limit: int) -> bytes:
    clean = assert_public_https(url)
    await assert_public_host(urlparse(clean).hostname or "")
    async with client.stream("GET", clean, follow_redirects=True, headers=_HEADERS) as response:
        response.raise_for_status()
        final = assert_public_https(str(response.url))
        await assert_public_host(urlparse(final).hostname or "")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > limit:
                raise ValueError("文件过大")
            chunks.append(chunk)
    return ensure_pdf(b"".join(chunks), limit)


async def save_open_pdfs(user_id: str, dois: list[str]) -> dict:
    from services.workspace_manager import MAX_FILE_SIZE, workspace_manager

    cleaned: list[str] = []
    for raw in dois or []:
        try:
            doi = clean_doi(str(raw))
        except ValueError:
            continue
        if doi not in cleaned:
            cleaned.append(doi)
        if len(cleaned) >= OPENALEX_PAGE:
            break
    if not cleaned:
        return {"saved": [], "skipped": [], "message": "先勾选有公开 PDF 的论文。"}
    saved: list[dict] = []
    skipped: list[dict] = []
    local = await workspace_manager.get_local_root(user_id)
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        for doi in cleaned:
            title = ""
            try:
                row = await _read_openalex_doi(client, doi)
                title = (row or {}).get("title") or ""
                url = (row or {}).get("pdf_url") or ""
                if not url:
                    skipped.append({"doi": doi, "title": title, "reason": "没有公开全文"})
                    continue
                data = await _download_pdf(client, url, MAX_FILE_SIZE)
                name = pdf_filename(title, doi)
                if local:
                    info = await workspace_manager.save_local_file(user_id, name, data)
                else:
                    info = await workspace_manager.save_user_file(user_id, name, data, "application/pdf")
                saved.append({
                    "doi": doi,
                    "title": title,
                    "name": info.get("name") or name,
                    "path": info.get("path") or "",
                })
            except ValueError as exc:
                skipped.append({"doi": doi, "title": title, "reason": str(exc) or "下载没有连上"})
            except (httpx.HTTPError, OSError):
                skipped.append({"doi": doi, "title": title, "reason": "下载没有连上"})
    return {"saved": saved, "skipped": skipped}


PASSAGE_QUERY_PROMPT = (
    "你只把用户贴来的文段变成文献检索词。"
    "不要写文献记录，不要编造作者、年份、DOI 或摘要。"
    "根据文段里涉及的问题、方法和会被引用的经典工作，写 1 到 3 条检索词。"
    "能对应到具体论文时，用这篇论文的英文题名。"
    "文段在准备计算机、Transformer、自注意力或大语言模型方面的论文时，检索词里要有 Attention Is All You Need。"
    "文段没有指向具体论文时，写研究者会拿去检索的英文短语，不要把整段原文当成检索词。"
    "每行一条，不要编号，不要解释。"
)


def parse_search_queries(text: str) -> list[str]:
    found: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().strip("*").strip()
        line = re.sub(r"^[\d]+[\.、\)]\s*", "", line)
        line = re.sub(r"^[-–]\s*", "", line)
        line = line.strip("「」\"'“”")
        if not line or len(line) > 160 or line.endswith(("：", ":")):
            continue
        if line not in found:
            found.append(line)
        if len(found) >= 3:
            break
    return found


def _passage_header(queries: list[str]) -> str:
    lines = ["用当前模型从这段文字拟了检索词："]
    lines.extend(f"{index}. {query}" for index, query in enumerate(queries, 1))
    return "\n".join(lines)


async def search_from_passage(
    passage: str,
    model_id: str,
    api_key: str,
    base_url: str,
    provider_id: str,
) -> dict:
    """先让当前模型从文段拟检索词，再向 OpenAlex 要真实记录。"""
    from providers import MODELS
    from services.idea_debate import _complete

    text = (passage or "").strip()
    if not text:
        return {
            "status": "empty",
            "provider": "openalex",
            "query": "",
            "items": [],
            "message": "先贴一段正在写的文字。",
        }
    name = next((item["name"] for item in MODELS if item["id"] == model_id), model_id)
    thinking, answer, err = await _complete(
        {"id": model_id, "name": name, "provider": provider_id},
        api_key,
        base_url,
        PASSAGE_QUERY_PROMPT,
        text[:4000],
        800,
    )
    if err:
        return _error(text[:80], err + " 没有编造文献。")
    queries = parse_search_queries(answer or thinking)
    if not queries:
        return {
            "status": "empty",
            "provider": "openalex",
            "query": "",
            "items": [],
            "message": "这段文字没有抽出检索词。可以写得更具体，或改用开放检索直接输入题名。没有编造文献。",
        }
    merged: list[dict] = []
    seen: set[str] = set()
    note = ""
    for query in queries:
        found = await search_openalex(query)
        if found.get("status") != "ok":
            note = found.get("message") or note
            continue
        for item in found.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = ((item.get("doi") or "") or (item.get("title") or "")).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= OPENALEX_PAGE:
                break
        if len(merged) >= OPENALEX_PAGE:
            break
    header = _passage_header(queries)
    if not merged:
        tail = note or "这几条检索词没有返回记录。没有编造文献。"
        return _error("；".join(queries), header + "\n\n" + tail)
    body = format_works("；".join(queries), merged, "OpenAlex 检索")
    return {
        "status": "ok",
        "provider": "openalex",
        "query": "；".join(queries),
        "items": merged,
        "message": header + "\n\n" + body,
    }


async def search_literature(query: str, source: str = "cnki", with_files: bool = False) -> dict:
    origin = (source or "cnki").strip().lower() or "cnki"
    if origin == "openalex":
        return await search_openalex(query, with_files)
    return reserved_literature(query, origin)

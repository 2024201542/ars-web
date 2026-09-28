"""查文献。知网只留接口；开放检索先问 OpenAlex。

关键词检索被限流时，用 Crossref 定位 DOI，再向 OpenAlex 读取同一条记录。
缺的字段留空，不编造。
"""

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


def format_works(query: str, items: list[dict], heading: str = "OpenAlex 检索") -> str:
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
            "",
        ])
    lines.append("以上是接口返回的记录。缺的字段留空，没有补写。")
    return "\n".join(lines).strip()


def _ok(query: str, items: list[dict], heading: str) -> dict:
    return {
        "status": "ok",
        "provider": "openalex",
        "query": query,
        "items": items,
        "message": format_works(query, items, heading),
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


async def _locate_then_read(client: httpx.AsyncClient, query: str) -> dict:
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
    return _ok(query, rows, heading)


async def search_openalex(query: str) -> dict:
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
                    return await _locate_then_read(client, text)
                except (httpx.HTTPError, ValueError):
                    return _error(text, "OpenAlex 这次检索太频繁，改走 Crossref 也没有连上。没有编造文献。")
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        return _error(text, f"OpenAlex 这次没有连上（{exc.response.status_code}）。没有编造文献。")
    except (httpx.HTTPError, ValueError) as exc:
        return _error(text, f"OpenAlex 这次没有连上（{type(exc).__name__}）。没有编造文献。")
    items = works_from_openalex(payload if isinstance(payload, dict) else {})
    return _ok(text, items, "OpenAlex 检索")


async def search_literature(query: str, source: str = "cnki") -> dict:
    origin = (source or "cnki").strip().lower() or "cnki"
    if origin == "openalex":
        return await search_openalex(query)
    return reserved_literature(query, origin)

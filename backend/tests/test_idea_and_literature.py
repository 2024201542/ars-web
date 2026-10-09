"""查文献只留接口；苏格拉底式提问一个模型即可，多模型辩论允许同一个接口。"""

from services.idea_debate import (
    _speech_prompt,
    _system,
    chat_completions_url,
    drain_debate_hints,
    latest_speeches,
    recent_socratic_turns,
    parse_topic_plan,
    summary_material,
    prepare_debate,
    push_debate_hint,
    voice_parts,
)
from services.literature_search import (
    PASSAGE_QUERY_PROMPT,
    _reject_ip,
    assert_public_https,
    ensure_pdf,
    format_works,
    open_pdf_url,
    parse_search_queries,
    reserved_literature,
    search_from_passage,
    search_literature,
    work_from_crossref,
    work_from_openalex,
    works_from_openalex,
)


READY = [
    {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "deepseek", "provider_name": "DeepSeek"},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "provider": "deepseek", "provider_name": "DeepSeek"},
    {"id": "kimi-k2-0905-preview", "name": "Kimi K2", "provider": "moonshot", "provider_name": "Kimi"},
]


def test_literature_stays_reserved():
    result = reserved_literature("记忆与物理教学", "cnki")
    assert result["status"] == "reserved"
    assert result["query"] == "记忆与物理教学"
    assert "不会编造" in result["message"]
    assert result["items"] == []


def test_openalex_records_keep_blank_fields():
    items = works_from_openalex({
        "results": [
            {
                "display_name": "Memory and teaching",
                "publication_year": 2021,
                "doi": "https://doi.org/10.1000/example",
                "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                "primary_location": {"source": {"display_name": "Journal of Memory"}},
            },
            {
                "display_name": "Only a title",
                "publication_year": None,
                "doi": None,
                "authorships": [],
                "primary_location": None,
            },
        ]
    })
    assert items[0]["doi"] == "10.1000/example"
    assert items[1]["authors"] == []
    assert items[1]["year"] == ""
    assert items[1]["source"] == ""
    assert items[1]["doi"] == ""
    text = format_works("memory", items)
    assert "Memory and teaching" in text
    assert "Ada Lovelace" in text
    assert "2021" in text
    assert "Journal of Memory" in text
    assert "10.1000/example" in text
    assert "2. Only a title\n作者：\n年份：\n来源：\nDOI：" in text
    assert "没有补写" in text


def test_open_pdf_ignores_landing_page_and_http():
    blocked = open_pdf_url({
        "best_oa_location": {"pdf_url": "http://example.com/a.pdf", "landing_page_url": "https://example.com/a"},
        "open_access": {"oa_url": "https://example.com/landing"},
    })
    assert blocked == ""
    opened = work_from_openalex({
        "display_name": "Attention Is All You Need",
        "best_oa_location": {"pdf_url": "https://arxiv.org/pdf/1706.03762"},
    })
    assert opened["pdf_url"] == "https://arxiv.org/pdf/1706.03762"
    blank = format_works("memory", [{"title": "Only a title", "authors": [], "year": "", "source": "", "doi": ""}], show_files=True)
    assert "全文：\n" in blank
    assert "全文：有公开 PDF" not in blank
    assert "不会下载" in blank
    _reject_ip("198.18.0.51")
    try:
        _reject_ip("10.1.2.3")
    except ValueError as exc:
        assert "不是公开" in str(exc)
    else:
        raise AssertionError("内网地址不应下载")
    try:
        assert_public_https("https://127.0.0.1/paper.pdf")
    except ValueError as exc:
        assert "不是公开" in str(exc)
    else:
        raise AssertionError("内网地址不应下载")
    try:
        ensure_pdf(b"<html>", 1000)
    except ValueError as exc:
        assert "不是 PDF" in str(exc)
    else:
        raise AssertionError("网页不应当成论文保存")


def test_crossref_locator_keeps_blank_fields():
    row = work_from_crossref({
        "title": ["Only a title"],
        "author": [],
        "issued": {},
        "container-title": [],
        "DOI": "",
    })
    assert row == {"title": "Only a title", "authors": [], "year": "", "source": "", "doi": ""}


def test_rate_limit_reads_openalex_by_doi(monkeypatch):
    import asyncio
    import httpx

    class FakeResponse:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                request = httpx.Request("GET", "https://example.test")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError("limited", request=request, response=response)

        def json(self):
            return self._payload

    async def fake_get(self, url, params=None, headers=None):
        if "api.openalex.org/works" in url and params and "search" in params:
            return FakeResponse(429, {})
        if "api.crossref.org" in url:
            return FakeResponse(200, {"message": {"items": [{
                "title": ["Memory and teaching"],
                "DOI": "10.1000/example",
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "issued": {"date-parts": [[2021]]},
                "container-title": ["Crossref Venue"],
            }]}})
        if url.endswith("/doi:10.1000/example"):
            return FakeResponse(200, {
                "display_name": "Memory and teaching",
                "publication_year": 2021,
                "doi": "https://doi.org/10.1000/example",
                "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                "primary_location": {"source": {"display_name": "Journal of Memory"}},
            })
        raise AssertionError(url)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    result = asyncio.run(search_literature("memory", "openalex"))
    assert result["status"] == "ok"
    assert result["items"][0]["source"] == "Journal of Memory"
    assert result["items"][0]["doi"] == "10.1000/example"
    assert "Crossref 定位" in result["message"]
    assert "Journal of Memory" in result["message"]
    assert "Crossref Venue" not in result["message"]


def test_parse_search_queries_keeps_distinct_titles():
    queries = parse_search_queries(
        "1. Attention Is All You Need\n"
        "Attention Is All You Need\n"
        "- transformer architecture\n"
        "检索词：\n"
        "第四条不要了"
    )
    assert queries == ["Attention Is All You Need", "transformer architecture", "第四条不要了"]
    assert "Attention Is All You Need" in PASSAGE_QUERY_PROMPT


def test_passage_search_uses_model_queries(monkeypatch):
    import asyncio

    async def fake_complete(model, key, base, system, user, max_tokens=1000):
        assert "Attention Is All You Need" in system
        assert "注意力" in user
        return "", "Attention Is All You Need\ntransformer architecture", ""

    seen = []

    async def fake_search(query, with_files=False):
        seen.append(query)
        if query == "Attention Is All You Need":
            return {"status": "ok", "items": [{
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani"],
                "year": 2017,
                "source": "NeurIPS",
                "doi": "10.48550/arXiv.1706.03762",
                "pdf_url": "",
            }]}
        return {"status": "ok", "items": [
            {
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani"],
                "year": 2017,
                "source": "NeurIPS",
                "doi": "10.48550/arXiv.1706.03762",
                "pdf_url": "",
            },
            {
                "title": "A survey of transformers",
                "authors": [],
                "year": 2022,
                "source": "",
                "doi": "10.1000/survey",
                "pdf_url": "",
            },
        ]}

    monkeypatch.setattr("services.idea_debate._complete", fake_complete)
    monkeypatch.setattr("services.literature_search.search_openalex", fake_search)
    result = asyncio.run(search_from_passage(
        "写一篇关于注意力机制的计算机论文",
        "deepseek-chat",
        "key",
        "https://api.deepseek.com",
        "deepseek",
    ))
    assert seen == ["Attention Is All You Need", "transformer architecture"]
    assert [item["title"] for item in result["items"]] == ["Attention Is All You Need", "A survey of transformers"]
    assert "拟了检索词" in result["message"]
    assert "Ashish Vaswani" in result["message"]
    assert result["message"].count("Attention Is All You Need") >= 2


def test_passage_without_queries_does_not_search(monkeypatch):
    import asyncio

    async def fake_complete(*args, **kwargs):
        return "", "", "DeepSeek Chat 没有返回（401）"

    async def fail_search(*args, **kwargs):
        raise AssertionError("模型没有给出检索词时不应检索")

    monkeypatch.setattr("services.idea_debate._complete", fake_complete)
    monkeypatch.setattr("services.literature_search.search_openalex", fail_search)
    result = asyncio.run(search_from_passage("一段文字", "deepseek-chat", "key", "", "deepseek"))
    assert result["items"] == []
    assert "没有编造文献" in result["message"]


def test_cnki_search_does_not_invent(monkeypatch):
    import asyncio
    import httpx

    def fail_get(*args, **kwargs):
        raise AssertionError("知网检索不应访问 OpenAlex")

    monkeypatch.setattr("httpx.AsyncClient.get", fail_get)
    result = asyncio.run(search_literature("记忆与物理教学", "cnki"))
    assert result["status"] == "reserved"
    assert result["items"] == []


def test_socratic_asks_one_question_and_keeps_turns():
    assert "一个问题" in _system("socratic")
    text = _speech_prompt("土地改革。我不确定", {}, [], False, "", False, True)
    assert "只问一个问题" in text
    turns = recent_socratic_turns([
        {"role": "user", "content": "主题是土地，看法是被绑上战船"},
        {"role": "assistant", "content": "已写完", "metadata": '{"debate":{"voices":[{"answer":"你说的绑上，是指哪一层？","kind":"speech"}]}}'},
    ])
    assert "用户：主题是土地" in turns
    assert "你说的绑上" in turns
    assert "已写完" not in turns


def test_socratic_uses_one_model():
    plan = prepare_debate("socratic", READY, [{"model": "deepseek-chat", "provider": "deepseek", "name": "DeepSeek Chat"}])
    assert plan["ok"] is True
    assert [item["id"] for item in plan["models"]] == ["deepseek-chat"]


def test_same_provider_can_debate():
    plan = prepare_debate("contrast", READY, [
        {"model": "deepseek-chat", "provider": "deepseek", "name": "DeepSeek Chat", "stance": "认为干预有效"},
        {"model": "deepseek-reasoner", "provider": "deepseek", "name": "DeepSeek Reasoner", "stance": "认为很难迁移"},
    ])
    assert plan["ok"] is True
    assert plan["models"][0]["stance"] == "认为干预有效"
    assert [item["id"] for item in plan["models"]] == ["deepseek-chat", "deepseek-reasoner"]


def test_debate_needs_two_models():
    plan = prepare_debate("contrast", READY, [{"model": "deepseek-chat", "provider": "deepseek", "name": "DeepSeek Chat"}])
    assert plan["ok"] is False
    assert "两个" in plan["text"]


def test_unknown_provider_is_skipped():
    plan = prepare_debate("socratic", READY, [{"model": "glm-5", "provider": "qwen", "name": "GLM-5"}])
    assert plan["ok"] is False


def test_topic_plan_splits_stances():
    plan = parse_topic_plan("【辩题】\n记忆能否被教学干预\n【看法】\ndeepseek-chat|可以\ndeepseek-reasoner|很难")
    assert plan["topic"] == "记忆能否被教学干预"
    assert plan["stances"]["deepseek-chat"] == "可以"


def test_judge_reads_both_rounds():
    voices = [
        {"model": "a", "name": "甲", "stance": "正方", "round": 1, "kind": "speech", "answer": "土地把农民绑上战船"},
        {"model": "b", "name": "乙", "stance": "反方", "round": 1, "kind": "speech", "answer": "农民因此获得土地"},
        {"model": "a", "name": "甲", "stance": "正方", "round": 2, "kind": "rebuttal", "answer": "获得土地仍是被绑上"},
        {"model": "c", "name": "法官", "round": 0, "kind": "judge", "answer": "旧判断"},
    ]
    kind, label, prompt = summary_material(voices, "judge", ["a", "b"])
    assert kind == "judge"
    assert label == "法官判断"
    assert "第1轮" in prompt and "第2轮" in prompt
    assert "土地把农民绑上战船" in prompt and "获得土地仍是被绑上" in prompt
    assert "旧判断" not in prompt
    assert "法官" in prompt and "原话" in prompt
    last_kind, last_label, last_prompt = summary_material(voices, "last", [])
    assert last_kind == "summary"
    assert last_label == "上一句"
    assert "获得土地仍是被绑上" in last_prompt
    assert "农民因此获得土地" not in last_prompt
    _, round_label, round_prompt = summary_material(voices, "rounds", [], [1])
    assert round_label == "第1轮"
    assert "土地把农民绑上战船" in round_prompt and "农民因此获得土地" in round_prompt
    assert "获得土地仍是被绑上" not in round_prompt
    _, speaker_label, speaker_prompt = summary_material(voices, "speaker", ["a"], [2])
    assert speaker_label == "甲的观点"
    assert "获得土地仍是被绑上" in speaker_prompt
    assert "土地把农民绑上战船" not in speaker_prompt


def test_summary_skips_a_later_summary_message():
    messages = [
        {"role": "assistant", "metadata": '{"debate":{"voices":[{"model":"a","answer":"第一句","kind":"speech"}]}}'},
        {"role": "assistant", "metadata": '{"debate":{"voices":[{"model":"b","answer":"这是总结","kind":"summary"}]}}'},
    ]
    speeches = latest_speeches(messages)
    assert speeches[0]["answer"] == "第一句"


def test_voice_keeps_reasoning_apart_from_answer():
    thinking, answer = voice_parts("【思考】先拆问题\n【回答】我会这样问", "")
    assert thinking == "先拆问题"
    assert answer == "我会这样问"
    thinking, answer = voice_parts("直接的看法", "隐藏的推理")
    assert thinking == "隐藏的推理"
    assert answer == "直接的看法"


def test_debate_prompt_rebuts_and_keeps_hint():
    text = _speech_prompt("记忆干预", {"stance": "有效"}, [{"name": "甲", "answer": "样本太小"}], True, "请盯住样本", True)
    assert "请盯住样本" in text
    assert "甲" in text
    assert "原话" in text
    assert "辩手" in _system("contrast")
    assert "写作教练" in _system("contrast")
    assert "修改意见" in _system("contrast")


def test_hint_is_read_once():
    push_debate_hint("s-hint", "往机制上辩")
    assert drain_debate_hints("s-hint") == "往机制上辩"
    assert drain_debate_hints("s-hint") == ""


def test_pause_waits_until_host_continues():
    import asyncio
    from services.idea_debate import hold_until_host, release_debate_gate

    async def scenario():
        async def pull():
            async for _evt in hold_until_host("gate-1", None):
                pass
        task = asyncio.create_task(pull())
        await asyncio.sleep(0.05)
        assert release_debate_gate("gate-1", "往定义上") is True
        await asyncio.wait_for(task, 3)
        assert drain_debate_hints("gate-1") == "往定义上"

    asyncio.run(scenario())


def test_excerpt_stops_at_cap():
    from services.idea_debate import SPEECH_CONTEXT_CHARS, clip_open_excerpt
    excerpt, total = clip_open_excerpt("甲" * (SPEECH_CONTEXT_CHARS + 20))
    assert total == SPEECH_CONTEXT_CHARS + 20
    assert len(excerpt) == SPEECH_CONTEXT_CHARS


def test_chat_url_appends_completions():
    assert chat_completions_url("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert chat_completions_url("https://api.moonshot.cn/v1") == "https://api.moonshot.cn/v1/chat/completions"

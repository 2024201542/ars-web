"""想法深入：苏格拉底式提问用一个模型；多模型辩论按顺序发言，同一个接口里的不同模型也可以。"""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from providers import MODELS, PROVIDERS

STYLES = {
    "socratic": "当前问法是苏格拉底式提问。用户会给出主题和自己的看法。不要替写作者下结论。采取问答：先用一两句接住他的看法，再只问一个问题，引导他自己往下想，并说明为什么问这一句。若上面已有问答，就顺着他刚说的那句再问下一个问题。不要一次抛出一串问题。",
    "contrast": "当前是多模型辩论。你是辩手。守住指定看法，只反驳其他辩手，不要改成写作指导。",
    "debate": "当前是多模型辩论。你是辩手。守住指定看法，只反驳其他辩手，不要改成写作指导。",
    "custom": "问法以用户这次写的话为准。按他指定的角度深入，不要改成另一套流程。",
}

_FORMAT = (
    "你在帮一位正在写论文的人把一个想法想深。用中文。"
    "必须按这个格式输出，不要加别的标题：\n"
    "【思考】\n推理过程\n【回答】\n给写作者看的内容"
)

_DEBATE_FORMAT = (
    "你是辩手，正在和其他模型辩论，不是写作教练。用中文。"
    "你能看见前面辩手的原话。必须点名，引用其中一句，再说明你同意或反对这句的理由。"
    "守住指定给你的看法。"
    "禁止给写作者改句子、列修改意见或教别人该怎么写。"
    "禁止出现这些说法：建议、应该这么说、可以改成、不妨写成、给作者的意见。"
    "必须按这个格式输出，不要加别的标题：\n"
    "【思考】\n写长，像辩论赛赛前拆题，分成四段，不要只写一两句。"
    "第一段定义辩题里的关键词；第二段写我方立论；第三段引用对方最强的一句原话；第四段写准备怎么拆。"
    "若还没有对方发言，第三段改为预判对方最可能的一句。\n"
    "【回答】\n用辩论赛上场的口气，称呼对方辩友。先亮明立场，再点名引用一句原话来反驳。"
    "回答比思考短。不要给写作者列修改意见。"
)

_HINTS: dict[str, list[str]] = {}
_GATES: dict[str, asyncio.Event] = {}
SPEECH_CONTEXT_CHARS = 2400


def clear_debate_hints(session_id: str) -> None:
    _HINTS.pop(session_id or "", None)


def push_debate_hint(session_id: str, text: str) -> None:
    cleaned = (text or "").strip()
    if not session_id or not cleaned:
        return
    _HINTS.setdefault(session_id, []).append(cleaned[:1000])


def drain_debate_hints(session_id: str) -> str:
    return "\n".join(_HINTS.pop(session_id or "", [])).strip()


def release_debate_gate(session_id: str, text: str = "") -> bool:
    """有方向就先记下。若正停在下一位之前，就放行。"""
    push_debate_hint(session_id, text)
    gate = _GATES.get(session_id or "")
    if gate:
        gate.set()
        return True
    return bool((text or "").strip())


def clip_open_excerpt(text: str) -> tuple[str, int]:
    raw = (text or "").strip()
    if not raw:
        return "", 0
    if len(raw) <= SPEECH_CONTEXT_CHARS:
        return raw, len(raw)
    return raw[:SPEECH_CONTEXT_CHARS], len(raw)


async def hold_until_host(session_id: str, cancel_event: asyncio.Event | None) -> AsyncIterator[dict]:
    """停在下一位之前，直到主持人继续或停止。等待时送心跳，避免连接被当成中断。"""
    gate = asyncio.Event()
    _GATES[session_id] = gate
    try:
        while not gate.is_set():
            if cancel_event and cancel_event.is_set():
                break
            yield {"event": "heartbeat", "data": {}}
            try:
                await asyncio.wait_for(gate.wait(), 12)
            except asyncio.TimeoutError:
                continue
    finally:
        _GATES.pop(session_id, None)


def split_marked(text: str) -> tuple[str, str]:
    raw = text or ""
    if "【思考】" in raw and "【回答】" in raw:
        thinking = raw.split("【思考】", 1)[1].split("【回答】", 1)[0].strip()
        answer = raw.split("【回答】", 1)[1].strip()
        return thinking, answer
    return "", raw.strip()


def voice_parts(content: str, reasoning: str = "") -> tuple[str, str]:
    marked_thinking, marked_answer = split_marked(content)
    thinking = (reasoning or marked_thinking).strip()
    if thinking:
        answer = (marked_answer or content or "").strip()
        if reasoning and "【回答】" in (content or ""):
            answer = marked_answer
        elif reasoning:
            answer = (content or "").strip()
        return thinking, answer
    return "", (content or "").strip()


def chat_completions_url(base: str) -> str:
    root = (base or "").rstrip("/")
    if root.endswith("/chat/completions"):
        return root
    return root + "/chat/completions"


def prepare_debate(mode: str, ready: list[dict], seats: list[dict]) -> dict:
    """苏格拉底式提问选一个模型。多模型辩论至少两个模型，同一个接口里的不同模型也可以。"""
    keyed = {item.get("provider") for item in ready}
    by_id = {item.get("id"): item for item in ready}
    picked = []
    seen = set()
    for seat in seats or []:
        model_id = (seat.get("model") or seat.get("id") or "").strip()
        provider_id = (seat.get("provider") or "").strip()
        if not model_id or model_id in seen or provider_id not in keyed:
            continue
        known = by_id.get(model_id) or {}
        if known and known.get("provider") != provider_id:
            continue
        picked.append({
            "id": model_id,
            "name": (seat.get("name") or known.get("name") or model_id).strip(),
            "provider": provider_id,
            "provider_name": known.get("provider_name") or "",
            "stance": (seat.get("stance") or "").strip(),
        })
        seen.add(model_id)
    kind = (mode or "").strip()
    if kind == "socratic":
        if not picked:
            return {"ok": False, "text": "苏格拉底式提问先选一个模型。", "models": []}
        return {"ok": True, "text": "", "models": picked[:1]}
    if kind in {"contrast", "debate"} and len(picked) < 2:
        return {"ok": False, "text": "多模型辩论至少选两个模型。同一个接口里的不同模型也可以。", "models": []}
    if not picked:
        return {"ok": False, "text": "先选一个模型。", "models": []}
    return {"ok": True, "text": "", "models": picked[:4]}


def parse_topic_plan(text: str) -> dict:
    raw = text or ""
    topic = ""
    stances: dict[str, str] = {}
    if "【辩题】" in raw:
        rest = raw.split("【辩题】", 1)[1]
        if "【看法】" in rest:
            head, tail = rest.split("【看法】", 1)
            topic = head.strip().splitlines()[0].strip() if head.strip() else ""
            for line in tail.splitlines():
                if "|" not in line:
                    continue
                model_id, stance = line.split("|", 1)
                model_id = model_id.strip()
                stance = stance.strip()
                if model_id and stance:
                    stances[model_id] = stance
        else:
            topic = rest.strip().splitlines()[0].strip() if rest.strip() else ""
    elif raw.strip():
        topic = raw.strip().splitlines()[0].strip()
    return {"topic": topic, "stances": stances}


def _style_line(mode_name: str) -> str:
    return STYLES.get(mode_name or "", STYLES["custom"])


def _system(mode_name: str) -> str:
    base = _DEBATE_FORMAT if (mode_name or "") in {"contrast", "debate"} else _FORMAT
    return base + "\n" + _style_line(mode_name)


def _extract_openai(payload: dict) -> tuple[str, str]:
    choice = ((payload or {}).get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content), str(message.get("reasoning_content") or "")


def _extract_anthropic(payload: dict) -> tuple[str, str]:
    blocks = (payload or {}).get("content") or []
    texts = []
    thinking = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "thinking":
            thinking.append(str(block.get("thinking") or ""))
        elif block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
    return "\n".join(texts).strip(), "\n".join(thinking).strip()


async def _complete(model: dict, key: str, base: str, system: str, user: str, max_tokens: int = 1000) -> tuple[str, str, str]:
    provider = PROVIDERS.get(model["provider"]) or {}
    timeout = httpx.Timeout(120.0 if max_tokens > 1000 else 90.0, connect=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if provider.get("protocol") == "anthropic":
                root = (base or "https://api.anthropic.com").rstrip("/")
                response = await client.post(
                    root + "/v1/messages",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model["id"],
                        "max_tokens": max_tokens,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                    },
                )
                if response.status_code >= 400:
                    return "", "", f"{model['name']} 没有返回（{response.status_code}）"
                content, reasoning = _extract_anthropic(response.json())
            else:
                response = await client.post(
                    chat_completions_url(base),
                    headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                    json={
                        "model": model["id"],
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": max_tokens,
                    },
                )
                if response.status_code >= 400:
                    return "", "", f"{model['name']} 没有返回（{response.status_code}）"
                content, reasoning = _extract_openai(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        return "", "", f"{model['name']} 没有连上：{type(exc).__name__}"
    thinking, answer = voice_parts(content, reasoning)
    if not answer and not thinking:
        return "", "", f"{model['name']} 没有写出内容"
    return thinking, answer, ""


def _card(model: dict, round_no: int, thinking: str, answer: str, error: str, kind: str = "speech") -> dict:
    return {
        "model": model["id"],
        "name": model["name"],
        "provider": model["provider"],
        "provider_name": model.get("provider_name") or "",
        "stance": model.get("stance") or "",
        "round": round_no,
        "kind": kind,
        "thinking": thinking,
        "answer": answer,
        "error": error,
    }


def recent_socratic_turns(messages: list[dict], limit: int = 6) -> str:
    rows: list[str] = []
    for message in messages or []:
        role = message.get("role")
        if role == "user":
            text = (message.get("content") or "").strip()
            label = "用户"
        elif role == "assistant":
            text = _spoken_answer(message)
            label = "提问"
        else:
            continue
        if not text:
            continue
        rows.append(f"{label}：{text[:500]}")
    return "\n\n".join(rows[-limit:])


def _spoken_answer(message: dict) -> str:
    raw = message.get("metadata") or ""
    try:
        meta = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        meta = {}
    voices = ((meta.get("debate") or {}).get("voices") or [])
    lines = [
        (item.get("answer") or "").strip()
        for item in voices
        if item.get("answer") and item.get("kind") not in {"summary", "judge"}
    ]
    if lines:
        return "\n".join(lines)
    return (message.get("content") or "").strip()


def _speech_prompt(topic: str, model: dict, prior: list[dict], rebuttal: bool, hint: str = "", debate: bool = False, socratic: bool = False) -> str:
    stance = (model.get("stance") or "").strip()
    heard = "\n\n".join(
        f"{item.get('name')}：{item.get('answer')}" for item in prior if item.get("answer") and not item.get("error")
    )
    lines = [f"辩题或想法：\n{topic}"]
    if stance:
        lines.append(f"你的看法：{stance}")
    if heard:
        lines.append(f"已经发言的结果：\n{heard}")
    if hint:
        lines.append(f"主持人在上一轮之后的意见，这一轮每个人都要看见，并顺着它继续互相反驳：\n{hint}")
    if debate and rebuttal:
        lines.append("你看得到上面每位的结果。点名并引用其中一句原话再反驳。不要教写作者该怎么改。先写【思考】，再写【回答】。")
    elif debate:
        lines.append("若上面已有别人的结果，就针对其中一句表态。还没有的话，只亮出你的主张和一条理由。不要写成写作建议。先写【思考】，再写【回答】。")
    elif socratic:
        lines.append("这是问答。先接住用户的主题和看法，再只问一个问题。先写【思考】，再写【回答】。回答里不要替他下结论。")
    elif rebuttal:
        lines.append("轮到你回应前面的发言。先写【思考】，再写【回答】。回答只写你的结论和理由。")
    else:
        lines.append("轮到你发言。先写【思考】，再写【回答】。回答只写给写作者看的结果。")
    return "\n\n".join(lines)


async def stream_debate(
    mode_name: str,
    user_message: str,
    models: list[dict],
    keys: dict[str, str],
    bases: dict[str, str],
    cancel_event: asyncio.Event | None = None,
    session_id: str = "",
    context_excerpt: str = "",
    context_total: int = 0,
    prior_turns: str = "",
) -> AsyncIterator[dict]:
    """一轮里依次发言，后发言的人看得见前面的结果。一轮结束后再等主持人的意见。"""
    system = _system(mode_name)
    topic = (user_message or "").strip()
    socratic = mode_name == "socratic"
    if socratic and prior_turns:
        topic = f"之前的问答：\n{prior_turns}\n\n这一次用户说：\n{topic}"
    if context_excerpt:
        topic += (
            f"\n\n打开的文稿，只带入前 {len(context_excerpt)} 字（全文 {context_total} 字）：\n{context_excerpt}"
        )
        yield {
            "event": "debate_context",
            "data": {"included": len(context_excerpt), "total": context_total, "cap": SPEECH_CONTEXT_CHARS},
        }
    debating = mode_name in {"contrast", "debate"}

    async def ask(model: dict, prompt: str, round_no: int, kind: str = "speech") -> dict:
        if cancel_event and cancel_event.is_set():
            return _card(model, round_no, "", "", "已停止", kind)
        thinking, answer, error = await _complete(
            model, keys.get(model["provider"]) or "", bases.get(model["provider"]) or "", system, prompt,
            2400 if debating else 1000,
        )
        return _card(model, round_no, thinking, answer, error, kind)

    async def pause_for_next_round() -> AsyncIterator[dict]:
        if not debating or not session_id:
            return
        yield {"event": "debate_pause", "data": {"name": "下一轮", "round": 2, "between": True}}
        async for beat in hold_until_host(session_id, cancel_event):
            yield beat

    if len(models) == 1:
        yield {"event": "phase_start", "data": {"phase": "tool", "description": f"正在听{models[0]['name']}"}}
        card = await ask(models[0], _speech_prompt(topic, models[0], [], False, "", debating, socratic), 1)
        yield {"event": "debate_voice", "data": card}
        yield {"event": "message", "data": {"delta": f"{models[0]['name']} 已写完。思考和结果分开，长的可以展开。"}}
        yield {"event": "done", "data": {"message": "完成"}}
        return

    spoken: list[dict] = []
    for index, model in enumerate(models, 1):
        if cancel_event and cancel_event.is_set():
            break
        yield {"event": "phase_start", "data": {"phase": "tool", "description": f"第 {index} 位：{model['name']}"}}
        card = await ask(model, _speech_prompt(topic, model, spoken, False, "", debating), 1)
        spoken.append(card)
        yield {"event": "debate_voice", "data": card}
    usable = [card for card in spoken if not card.get("error")]
    if len(usable) < 2 or (cancel_event and cancel_event.is_set()):
        yield {"event": "message", "data": {"delta": "这一轮先停在这里。要继续，可以换一位来总结，或再发一句。"}}
        yield {"event": "done", "data": {"message": "完成"}}
        return
    async for evt in pause_for_next_round():
        yield evt
    if cancel_event and cancel_event.is_set():
        yield {"event": "done", "data": {"message": "完成"}}
        return
    host_note = drain_debate_hints(session_id) if session_id else ""
    for model in models:
        if cancel_event and cancel_event.is_set():
            break
        if any(card.get("model") == model["id"] and card.get("error") for card in spoken):
            continue
        yield {"event": "phase_start", "data": {"phase": "tool", "description": f"{model['name']} 回应"}}
        others = [item for item in spoken if item.get("model") != model["id"]]
        card = await ask(model, _speech_prompt(topic, model, others, True, host_note, debating), 2)
        spoken.append(card)
        yield {"event": "debate_voice", "data": card}
    names = "、".join(card["name"] for card in usable)
    yield {"event": "message", "data": {"delta": f"{names} 已按顺序发过言。思考和结果分开，长的可以展开。"}}
    yield {"event": "done", "data": {"message": "完成"}}


async def stream_topic(model: dict, idea: str, participants: list[dict], keys: dict, bases: dict) -> AsyncIterator[dict]:
    names = "\n".join(f"{item['id']}|{item['name']}" for item in participants)
    prompt = (
        f"写作者的看法：\n{idea}\n\n参加辩论的模型：\n{names}\n\n"
        "请把它收成一个可以辩论的题目，并给每个模型指定不同看法。"
        "严格按这个格式，不要加别的标题：\n【辩题】\n一句话\n【看法】\n模型id|这个模型的看法"
    )
    thinking, answer, error = await _complete(
        model, keys.get(model["provider"]) or "", bases.get(model["provider"]) or "", _FORMAT, prompt,
    )
    if error:
        yield {"event": "message", "data": {"delta": error}}
        yield {"event": "done", "data": {"message": "完成"}}
        return
    plan = parse_topic_plan(answer or thinking)
    yield {"event": "debate_topic", "data": plan}
    text = plan["topic"] or "辩题已经拟好。"
    yield {"event": "message", "data": {"delta": f"辩题：{text}\n可以改看法，再开始辩论。"}}
    yield {"event": "done", "data": {"message": "完成"}}


def summary_material(voices: list[dict], scope: str, pair: list[str], rounds: list[int] | None = None) -> tuple[str, str, str]:
    chosen = [item for item in voices if item.get("kind") not in {"summary", "judge"} and item.get("answer")]
    wanted = [item for item in (pair or []) if item]
    round_set: set[int] = set()
    for item in rounds or []:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            round_set.add(number)
    if scope == "rounds":
        if not round_set:
            return "", "", ""
        chosen = [item for item in chosen if int(item.get("round") or 0) in round_set]
    elif scope == "speaker":
        one = wanted[0] if wanted else ""
        chosen = [item for item in chosen if item.get("model") == one]
        if round_set:
            chosen = [item for item in chosen if int(item.get("round") or 0) in round_set]
    elif scope == "pair" or (scope == "judge" and len(wanted) >= 2):
        chosen = [item for item in chosen if item.get("model") in set(wanted)]
        if scope == "judge" and round_set:
            chosen = [item for item in chosen if int(item.get("round") or 0) in round_set]
    elif scope == "judge" and round_set:
        chosen = [item for item in chosen if int(item.get("round") or 0) in round_set]
    elif scope != "judge" and chosen:
        chosen = chosen[-1:]
    if not chosen:
        return "", "", ""
    lines = []
    for item in chosen:
        round_no = int(item.get("round") or 0)
        head = f"第{round_no}轮 " if round_no else ""
        who = item.get("name") or item.get("model") or ""
        stance = (item.get("stance") or "").strip()
        if stance:
            who = f"{who}（{stance}）"
        lines.append(f"{head}{who}：{item.get('answer')}")
    body = "\n\n".join(lines)
    if scope == "judge":
        return "judge", "法官判断", (
            "你是这场辩论的法官，不是辩手，也不是写作教练。只根据下面各轮的原话判断。\n"
            "【思考】按轮次写：每一轮双方最强的一句原话，谁回应了谁，有没有离题。\n"
            "【回答】用法官口吻宣布。点名引用双方原话，说明谁更有说服力，理由只来自这些发言。"
            "不要给写作者列修改意见，不要再开一轮辩论。\n\n"
            + body
        )
    if scope == "speaker":
        who = chosen[0].get("name") or chosen[0].get("model") or "这位"
        label = f"{who}的观点"
        return "summary", label, (
            f"请只整理{who}的观点。按轮次写，不要替其他人发言，不要展开成新的论文。"
            "先写【思考】，再写【回答】。\n\n"
            + body
        )
    if scope == "rounds":
        nums = "、".join(f"第{number}轮" for number in sorted(round_set))
        label = nums or "所选轮次"
        return "summary", label, (
            f"请整理{label}。每一轮分开写各方观点，再写他们争的是什么。不要展开成新的论文。"
            "先写【思考】，再写【回答】。\n\n"
            + body
        )
    label = "上一句" if scope != "pair" else "这两位的交锋"
    return "summary", label, f"请总结{label}。按发言里的轮次来说，不要展开成新的论文。先写【思考】，再写【回答】。\n\n{body}"


async def stream_summary(model: dict, voices: list[dict], scope: str, pair: list[str], keys: dict, bases: dict, rounds: list[int] | None = None) -> AsyncIterator[dict]:
    kind, label, prompt = summary_material(voices, scope, pair, rounds)
    if not prompt:
        yield {"event": "message", "data": {"delta": "还没有可以总结的发言。"}}
        yield {"event": "done", "data": {"message": "完成"}}
        return
    thinking, answer, error = await _complete(
        model, keys.get(model["provider"]) or "", bases.get(model["provider"]) or "", _system("custom"), prompt,
    )
    card = _card(model, 0, thinking, answer, error, kind)
    yield {"event": "debate_voice", "data": card}
    done = f"{model['name']} 已作出{label}。" if kind == "judge" else f"{model['name']} 已总结{label}。"
    yield {"event": "message", "data": {"delta": done}}
    yield {"event": "done", "data": {"message": "完成"}}


def latest_speeches(messages: list[dict]) -> list[dict]:
    for message in reversed(messages or []):
        if message.get("role") != "assistant":
            continue
        raw = message.get("metadata") or ""
        try:
            meta = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            continue
        voices = (meta.get("debate") or {}).get("voices") or []
        speeches = [item for item in voices if item.get("kind") not in {"summary", "judge"} and item.get("answer")]
        if speeches:
            return speeches
    return []


def model_catalog() -> list[dict]:
    rows = []
    for item in MODELS:
        provider = PROVIDERS[item["provider"]]
        rows.append({
            "id": item["id"],
            "name": item["name"],
            "provider": item["provider"],
            "provider_name": provider["display_name"],
        })
    return rows

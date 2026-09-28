"""全流程按步推进，文件落在 @ 的文件夹里。"""

from services.pipeline_steps import STEPS, resolve_pipeline


DIRS = [{"path": "记忆方法论文写作", "name": "记忆方法论文写作", "is_dir": True}]


def test_without_folder_asks_first():
    plan = resolve_pipeline([], "写一篇关于记忆的论文", "", DIRS)
    assert plan["skip_model"] is True
    assert "文件夹" in plan["text"]
    assert plan["pipeline"]["need_folder"] is True


def test_topic_with_folder_lists_steps_and_waits():
    plan = resolve_pipeline([], "@记忆方法论文写作 写一篇关于记忆的论文", "", DIRS)
    assert plan["skip_model"] is True
    assert plan["pipeline"]["index"] == -1
    assert plan["pipeline"]["awaiting"] is True
    assert plan["pipeline"]["next_label"] == "快速简报"
    assert "11-论文终稿.md" in plan["text"]
    assert "还没有开始写" in plan["text"]
    assert plan["pipeline"]["topic"] == "写一篇关于记忆的论文"


def test_start_button_runs_only_the_first_step():
    prior = {
        "role": "assistant",
        "metadata": '{"pipeline":{"index":-1,"awaiting":true,"done":false,"folder":"记忆方法论文写作","topic":"写一篇关于记忆的论文"}}',
    }
    plan = resolve_pipeline([prior], "开始", "continue", DIRS)
    assert plan["skip_model"] is False
    assert plan["pipeline"]["index"] == 0
    assert plan["pipeline"]["file"] == "记忆方法论文写作/01-研究简报.md"
    assert "写一篇关于记忆的论文" in plan["model_prompt"]
    assert "只做第 1/" in plan["model_prompt"]


def test_folder_reply_keeps_topic_and_waits():
    prior = {
        "role": "assistant",
        "metadata": '{"pipeline":{"index":-1,"awaiting":false,"need_folder":true,"folder":"","topic":"写记忆"}}',
    }
    plan = resolve_pipeline([prior], "@记忆方法论文写作", "", DIRS)
    assert plan["skip_model"] is True
    assert plan["pipeline"]["awaiting"] is True
    assert plan["pipeline"]["folder"] == "记忆方法论文写作"
    assert plan["pipeline"]["topic"] == "写记忆"


def test_confirm_advances_and_keeps_folder():
    prior = {
        "role": "assistant",
        "metadata": '{"pipeline":{"index":0,"awaiting":true,"done":false,"folder":"记忆方法论文写作"}}',
    }
    plan = resolve_pipeline([prior], "确认，继续下一步", "continue", DIRS)
    assert plan["pipeline"]["index"] == 1
    assert plan["pipeline"]["label"] == "文献综述"
    assert plan["pipeline"]["file"] == "记忆方法论文写作/02-文献综述.md"


def test_note_while_waiting_repeats_same_step():
    prior = {
        "role": "assistant",
        "metadata": '{"pipeline":{"index":3,"awaiting":true,"done":false,"folder":"记忆方法论文写作"}}',
    }
    plan = resolve_pipeline([prior], "大纲再细一点", "", DIRS)
    assert plan["pipeline"]["index"] == 3
    assert "再细一点" in plan["mode_line"]


def test_asking_for_final_after_done_does_not_restart():
    prior = {
        "role": "assistant",
        "metadata": '{"pipeline":{"index":9,"awaiting":false,"done":true,"folder":"22","topic":"短视频与学习"}}',
    }
    plan = resolve_pipeline([prior], "终稿在哪。最后给我一个终稿文件", "", [{"path": "22", "name": "22", "is_dir": True}])
    assert plan["skip_model"] is False
    assert plan["pipeline"]["label"] == "终稿"
    assert plan["pipeline"]["index"] == len(STEPS) - 1
    assert plan["pipeline"]["file"] == "22/11-论文终稿.md"
    assert "01-研究简报" not in plan["pipeline"]["file"]


def test_new_topic_after_done_waits_again():
    prior = {
        "role": "assistant",
        "metadata": '{"pipeline":{"index":10,"awaiting":false,"done":true,"folder":"记忆方法论文写作","topic":"旧题目"}}',
    }
    plan = resolve_pipeline([prior], "@记忆方法论文写作 再写一篇关于睡眠的", "", DIRS)
    assert plan["skip_model"] is True
    assert plan["pipeline"]["index"] == -1
    assert plan["pipeline"]["topic"] == "再写一篇关于睡眠的"


def test_last_step_does_not_ask_to_continue():
    prior = {
        "role": "assistant",
        "metadata": '{"pipeline":{"index":9,"awaiting":true,"done":false,"folder":"记忆方法论文写作","topic":"记忆"}}',
    }
    plan = resolve_pipeline([prior], "确认，继续下一步", "continue", DIRS)
    assert plan["pipeline"]["index"] == len(STEPS) - 1
    assert plan["pipeline"]["label"] == "终稿"
    assert plan["pipeline"]["done"] is True
    assert plan["pipeline"]["awaiting"] is False
    assert plan["pipeline"]["file"].endswith("11-论文终稿.md")
    assert "记忆" in plan["model_prompt"]

"""测试 skill_loader.py —— 技能加载与解析"""

import pytest
from services.skill_loader import SkillLoader, _parse_frontmatter


class TestParseFrontmatter:
    """YAML frontmatter 解析测试"""

    def test_with_frontmatter(self):
        content = "---\nname: test\ndescription: A test skill\n---\n\n# Body\nSome content"
        meta, body = _parse_frontmatter(content)
        assert meta == {"name": "test", "description": "A test skill"}
        assert "# Body" in body
        assert "Some content" in body

    def test_without_frontmatter(self):
        content = "# Just a markdown file\n\nNo frontmatter here."
        meta, body = _parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_empty_file(self):
        meta, body = _parse_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_malformed_yaml(self):
        content = "---\ninvalid: yaml: here\n---\nbody"
        meta, body = _parse_frontmatter(content)
        assert meta == {}  # 解析失败时返回空 dict
        assert "body" in body


class TestSkillLoader:
    """技能加载器测试（使用真实 ARS 路径）"""

    @pytest.fixture
    def loader(self):
        return SkillLoader()

    def test_get_skills_returns_list(self, loader):
        skills = loader.get_skills()
        assert isinstance(skills, list)
        assert len(skills) >= 3  # 至少有 deep-research, academic-paper, reviewer
        for s in skills:
            assert "name" in s
            assert "display_name" in s
            assert "modes" in s
            assert "icon" in s

    def test_known_skill_has_modes(self, loader):
        modes = loader.get_skill_modes("deep-research")
        assert isinstance(modes, list)
        assert len(modes) >= 3
        for m in modes:
            assert "name" in m
            assert "display_name" in m
            assert "phases" in m

    def test_unknown_skill_returns_empty(self, loader):
        modes = loader.get_skill_modes("nonexistent-skill")
        assert modes == []

    def test_get_skill_config_academic_paper(self, loader):
        config = loader.get_skill_config("academic-paper")
        assert "paper_types" in config
        assert "citation_formats" in config
        assert "output_formats" in config

    def test_get_skill_config_deep_research_has_output_formats(self, loader):
        config = loader.get_skill_config("deep-research")
        assert "output_formats" in config

    def test_get_agent_system_prompt_known_skill(self, loader):
        prompt = loader.get_agent_system_prompt("deep-research")
        assert isinstance(prompt, str)
        assert len(prompt) > 1000  # ARS SKILL.md 是长文档

    def test_get_agent_system_prompt_unknown_skill(self, loader):
        prompt = loader.get_agent_system_prompt("nonexistent")
        assert isinstance(prompt, str)
        assert "助手" in prompt  # 回退提示词

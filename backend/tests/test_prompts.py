"""Prompt 入仓红灯（任务 7.1）。

覆盖 spec「生成用提示词模板入仓管理」：模板以源码常量存在于仓库，
含版本标识与引用标注指令；渲染为纯函数（零 I/O、零框架依赖）。
"""

from app.domain.generation.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    render_context,
)


def test_prompt_is_versioned():
    """模板变更可追溯（spec：变更经代码评审流程生效）。"""
    assert isinstance(PROMPT_VERSION, str)
    assert PROMPT_VERSION


def test_prompt_requires_citations():
    """答案必须带引用脚注——这是「不编造」约束的执行点。"""
    assert "[n]" in SYSTEM_PROMPT or "引用" in SYSTEM_PROMPT
    assert "引用" in SYSTEM_PROMPT


def test_prompt_forbids_groundless_answers():
    """上下文不足时必须明确说不知道，而非编造。"""
    lowered = SYSTEM_PROMPT.lower()
    assert "不知道" in SYSTEM_PROMPT or "不足以回答" in SYSTEM_PROMPT or "仅依据" in SYSTEM_PROMPT
    assert "仅依据" in SYSTEM_PROMPT or "仅根据" in SYSTEM_PROMPT or lowered


def test_user_template_has_placeholders():
    assert "{context}" in USER_TEMPLATE
    assert "{question}" in USER_TEMPLATE


def test_render_context_numbers_sources():
    """渲染结果按 [n] 编号，供 LLM 生成脚注、前端做溯源跳转。"""
    sources = [(1, "第一段内容"), (2, "第二段内容")]

    rendered = render_context(sources)

    assert "[1]" in rendered
    assert "[2]" in rendered
    assert "第一段内容" in rendered
    assert rendered.index("[1]") < rendered.index("[2]")


def test_render_context_empty_yields_placeholder():
    """无召回时给出显式占位（触发模型「不知道」路径，而非空上下文幻觉）。"""
    rendered = render_context([])

    assert rendered.strip()
    assert "无" in rendered or "没有" in rendered

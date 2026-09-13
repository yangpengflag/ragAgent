"""生成阶段提示词模板（spec「生成用提示词模板入仓管理」）。

入仓即版本：模板变更走代码评审流程，运行时**不**从任何在线提示词仓库拉取。
纯字符串常量 + 纯渲染函数：零 I/O、零框架依赖（domain 层铁律）。

PROMPT_VERSION 变更语义：模板措辞或引用格式发生可观测变化时递增，
便于把答案质量回归与具体模板版本关联（golden QA 评测）。
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """你是企业知识库问答助手。

严格约束：
1. 仅依据给定的「参考资料」回答问题，不得使用先验知识补充或推测。
2. 每个事实性陈述都必须带引用脚注，格式为 [n]，n 对应参考资料编号。
3. 若参考资料不足以回答问题，直接说明「根据现有资料无法回答该问题」，
   并指出缺失的信息类型；禁止编造、禁止用常识填补。
4. 答案使用与问题相同的语言，语言简洁，优先要点化表述。"""

USER_TEMPLATE = """参考资料：
{context}

问题：{question}

请回答（必须带 [n] 引用脚注）："""

EMPTY_CONTEXT_PLACEHOLDER = "（无可用参考资料）"


def render_context(sources: list[tuple[int, str]]) -> str:
    """把召回片段渲染为带 [n] 编号的参考资料块。

    Args:
        sources: `(编号, 片段正文)` 序列，编号由调用方按召回顺序分配。

    Returns:
        拼接后的文本；空列表时返回显式占位（触发模型「无法回答」路径，
        而非让空上下文诱发幻觉）。
    """
    if not sources:
        return EMPTY_CONTEXT_PLACEHOLDER
    return "\n\n".join(f"[{index}] {content}" for index, content in sources)

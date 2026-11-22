"""校验问题的统一构造与错误码。"""

from __future__ import annotations

from .models import Issue, IssueLevel


# 错误码集中维护，分谱与总报告都引用同一套码
UNSLOTTABLE = "UNSLOTTABLE"            # 可起音拍位不足，音节挤入不可拆单音位
GROUP_BAR_MISMATCH = "GROUP_BAR_MISMATCH"
CODA_MISMATCH = "CODA_MISMATCH"        # 共有尾音落点对不上
REENTRY_MISMATCH = "REENTRY_MISMATCH"  # 换气后再进入拍点对不上
MARK_NO_PLACEMENT = "MARK_NO_PLACEMENT"
STRESS_LOCK = "STRESS_LOCK"            # 已约定重音被新唱法移动
NEGATION_SCOPE = "NEGATION_SCOPE"      # 换气割裂否定作用域
READING_UNKNOWN = "READING_UNKNOWN"
SECTION_BLOCKED = "SECTION_BLOCKED"    # 共享段无法兼容，退回声部确认


def make_issue(code: str, level: IssueLevel, message: str, *,
               voices: tuple[str, ...] = (), section: str | None = None,
               bars: tuple[int, ...] = (), note_ids: tuple[str, ...] = ()) -> Issue:
    return Issue(
        code=code,
        level=level,
        voices=tuple(voices),
        section=section,
        bars=tuple(bars),
        message=message,
        note_ids=tuple(note_ids),
    )


def error(code: str, message: str, **kwargs) -> Issue:
    return make_issue(code, IssueLevel.ERROR, message, **kwargs)


def warning(code: str, message: str, **kwargs) -> Issue:
    return make_issue(code, IssueLevel.WARNING, message, **kwargs)

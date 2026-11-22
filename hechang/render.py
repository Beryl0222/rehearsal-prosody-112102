"""渲染：分声部分谱、教师总报告、钢琴/指导总览与机器可读清单。

所有分谱抬头都带同一个 selection_id：负责人选定后，各声部拿到的分谱
必然对应同一次选择。分谱每个落字都带 words 记录 id 与字符下标，
更正发生时可以从原词直接找到需要重练的位置。
"""

from __future__ import annotations

from .models import Arrangement, Plan, SegmentVerdict
from .phonology import landing


def render_part_score(plan: Plan, corpus, voice: str) -> str:
    arrangements = [a for a in plan.arrangements if a.voice == voice]
    lines = [
        f"分谱 · {voice}",
        f"方案选择：{plan.selection_id}（与其他声部同一次选择，请勿混用旧版）",
        f"依据笔记 at：{', '.join(map(str, plan.created_from_notes))}",
        "=" * 64,
    ]
    rendered_sections: set[str] = set()
    for arrangement in arrangements:
        rendered_sections.add(arrangement.section)
        verdict = _verdict_of(plan, arrangement.section, arrangement.voice)
        tag = verdict.status.value if verdict else ""
        lines.append(f"【{arrangement.section}】小节 {_bar_range(arrangement)}  {tag}")
        if arrangement.region:
            lines.append(f"  选定唱法：{arrangement.reading_id}（{arrangement.region}）")
        else:
            lines.append(f"  选定唱法：{arrangement.reading_id}（字面）")
        current_bar = None
        for placement in arrangement.placements:
            if placement.bar != current_bar:
                current_bar = placement.bar
                slots = corpus.score_bar(voice, current_bar).slots
                lines.append(f"  第{current_bar}小节 拍位：{_slot_line(slots)}")
            mark = []
            if placement.stress:
                mark.append("重音")
            if placement.entering:
                mark.append("入声收短")
            # 辅音落点只对记音音节（拉丁字母）展示；字面汉字不展示
            if any("a" <= ch.lower() <= "z" for ch in placement.syllable):
                mark.append(f"辅音落点={landing(placement.syllable)}")
            mark_str = "（" + "，".join(mark) + "）"
            lines.append(
                f"    {placement.beat:>5}  {placement.word_surface or placement.token.text}"
                f" · {placement.syllable} {mark_str}"
                f"  [{_locator(corpus, arrangement, placement)}]"
            )
        lines.append("  词界：" + " | ".join(
            _word_boundary_text(arrangement)
        ))
        if arrangement.legal_breaths:
            lines.append("  合法换气：")
            for beat, reason in arrangement.legal_breaths:
                lines.append(f"    - {beat}：{reason}")
        if arrangement.blocked_breaths:
            lines.append("  禁止换气（改变听众理解）：")
            for beat, reason in arrangement.blocked_breaths:
                lines.append(f"    - {beat}：{reason}")
        lines.append("")

    # 没有安排的段（被阻断）也要在分谱上交代清楚，学员知道哪里在等确认
    for verdict in plan.verdicts:
        if verdict.voice not in (voice, None):
            continue
        if verdict.section in rendered_sections:
            continue
        lines.append(f"【{verdict.section}】小节 {_tuple_range(verdict.bars)}  "
                     f"{verdict.status.value}")
        lines.append(f"  说明：{verdict.message}")
        for issue in verdict.issues[:4]:
            lines.append(f"  · {issue.level.value.upper()} {issue.code}：{issue.message}")
        lines.append("  本谱暂不包含该段落字，确认后随下一版方案补发。")
        lines.append("")

    lines.append("已排练/新安排区分见教师总报告与『重练提示』；"
                 "未列出的备选唱法见教师总报告。")
    return "\n".join(lines) + "\n"


def render_conductor_report(plan: Plan, corpus) -> str:
    lines = [
        "教师总报告 · 联合试唱方案",
        f"方案选择：{plan.selection_id}",
        f"整体可用性：{'可联合试唱' if plan.usable else '本次无法组成可用新版，问题交回老师'}",
        f"可发学员继续练的段：{('、'.join(plan.practice_ready_sections)) or '无'}",
        "=" * 64,
    ]
    for verdict in plan.verdicts:
        scope = f"{verdict.voice} " if verdict.voice else "合唱 "
        lines.append(
            f"[{verdict.status.value}] {scope}{verdict.section}（小节 {_tuple_range(verdict.bars)}）"
        )
        if verdict.reading_id:
            lines.append(f"  唱法：{verdict.reading_id} {verdict.region or ''}".rstrip())
        lines.append(f"  说明：{verdict.message}")
        if verdict.note_ids:
            lines.append(f"  相关笔记：{', '.join(verdict.note_ids)}")
        for issue in verdict.issues:
            lines.append(f"  · {issue.level.value.upper()} {issue.code}：{issue.message}")
        lines.append("")

    if plan.alternatives:
        lines.append("未达成一致 / 被保留的备选唱法：")
        for alt in plan.alternatives:
            lines.append(
                f"  - {alt.voice} {alt.section} {alt.reading_id}（{alt.region}）"
                f" 未采用原因：{', '.join(alt.rejected_for)}；笔记 {', '.join(alt.note_ids)}"
            )
        lines.append("")

    warnings = [i for i in plan.issues if i.level.value == "warning"]
    if warnings:
        lines.append("语义与换气提示：")
        for issue in warnings:
            lines.append(f"  · {issue.code}：{issue.message}")
    return "\n".join(lines)


def render_piano_overview(plan: Plan, corpus) -> str:
    """钢琴伴奏与指导教师视图：按小节横向对齐各声部落点。"""

    lines = [
        "钢琴伴奏 / 指导总览",
        f"方案选择：{plan.selection_id}",
        "=" * 64,
    ]
    sections = list(corpus.sections)
    for section in sections:
        bars = corpus.sections[section]
        voices = corpus.voices_in_section(section)
        lines.append(f"【{section}】小节 {_int_range(bars)}")
        for bar in bars:
            lines.append(f"  第{bar}小节")
            for voice in voices:
                arrangement = next(
                    (a for a in plan.arrangements
                     if a.voice == voice and a.section == section), None
                )
                if arrangement is None:
                    reason = _block_reason(plan, section)
                    lines.append(f"    {voice}：（本方案无安排：{reason}）")
                    continue
                placed = arrangement.placements_in_bar(bar)
                text = "  ".join(
                    f"{p.beat}={p.syllable}{'*' if p.stress else ''}"
                    f"{'!' if p.entering else ''}" for p in placed
                )
                lines.append(f"    {voice}：{text}")
        lines.append("")
    return "\n".join(lines)


def render_manifest(plan: Plan, corpus) -> dict:
    """机器可读清单：一次选择、逐段状态、逐声部唱法与原词定位。"""

    return {
        "selection_id": plan.selection_id,
        "usable": plan.usable,
        "created_from_notes": list(plan.created_from_notes),
        "practice_ready_sections": list(plan.practice_ready_sections),
        "segments": [
            {
                "section": v.section,
                "bars": list(v.bars),
                "voice": v.voice,
                "status": v.status.value,
                "reading_id": v.reading_id,
                "region": v.region,
                "note_ids": list(v.note_ids),
                "issues": [
                    {"code": i.code, "level": i.level.value, "message": i.message}
                    for i in v.issues
                ],
            }
            for v in plan.verdicts
        ],
        "arrangements": [
            {
                "voice": a.voice,
                "section": a.section,
                "bars": a.bars,
                "reading_id": a.reading_id,
                "region": a.region,
                "placements": [
                    {
                        "beat": p.beat,
                        "bar": p.bar,
                        "surface": p.word_surface,
                        "syllable": p.syllable,
                        "stress": p.stress,
                        "entering": p.entering,
                        "landing": (
                            landing(p.syllable)
                            if any("a" <= ch.lower() <= "z" for ch in p.syllable)
                            else "∅"
                        ),
                        "word_id": _locator_word_id(corpus, a, p),
                        "char_index": p.token.index,
                    }
                    for p in a.placements
                ],
                "legal_breaths": [{"beat": b, "reason": r} for b, r in a.legal_breaths],
                "blocked_breaths": [{"beat": b, "reason": r} for b, r in a.blocked_breaths],
            }
            for a in plan.arrangements
        ],
        "alternatives": [
            {
                "section": alt.section, "bars": list(alt.bars), "voice": alt.voice,
                "reading_id": alt.reading_id, "region": alt.region,
                "rejected_for": list(alt.rejected_for), "note_ids": list(alt.note_ids),
            }
            for alt in plan.alternatives
        ],
    }


def render_repractice_note(trace: dict) -> str:
    lines = [
        f"重练提示 · 更正笔记 {trace['note_id']}（{trace['action']}）",
        f"方案选择：{trace['selection_id']}  声部：{trace['voice']}  词条：{trace['surface']}",
        "-" * 64,
    ]
    for item in trace["items"]:
        if item["status"] == "blocked":
            flag = "该段待声部确认，确认前不重练"
        elif item["status"] == "no_baseline":
            flag = "需重练" if item["repractice"] else "原词格落不下，等待新安排"
        else:
            flag = "需重练" if item["repractice"] else "落点未变，无需重练"
        lines.append(
            f"- {item['section']} 第{('、'.join(map(str, item['bars'])))}小节"
            f"（第 {item['ordinal']} 次出现，原词记录 {item['word_id']}，"
            f"字符下标 {item['indices']}，小句『{item['context']}』）"
        )
        lines.append(
            f"    已排练落点：{item['rehearsed_beat'] or '（无合法原词格）'} "
            f"→ 新安排落点：{item['new_beat'] or '（待确认）'}  [{flag}]"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------- 辅助


def _verdict_of(plan: Plan, section: str, voice: str) -> SegmentVerdict | None:
    for verdict in plan.verdicts:
        if verdict.section == section and verdict.voice in (voice, None):
            return verdict
    return None


def _block_reason(plan: Plan, section: str) -> str:
    for verdict in plan.verdicts:
        if verdict.section == section and verdict.issues:
            return verdict.issues[0].code
    return "等待确认"


def _bar_range(arrangement: Arrangement) -> str:
    return _int_range(arrangement.bars)


def _int_range(bars: list[int]) -> str:
    if len(bars) == 1:
        return str(bars[0])
    return f"{bars[0]}-{bars[-1]}"


def _tuple_range(bars: tuple[int, ...]) -> str:
    return _int_range(list(bars))


def _slot_line(slots) -> str:
    return " ".join(
        f"{s.beat}{'*' if s.can_start else '×'}" for s in slots
    )


def _word_boundary_text(arrangement: Arrangement) -> list[str]:
    by_index = {p.token.index: p for p in arrangement.placements}
    out = []
    for index in arrangement.word_boundaries:
        placement = by_index.get(index)
        if placement:
            out.append(f"{placement.word_surface}@{placement.beat}")
    return out


def _locator(corpus, arrangement: Arrangement, placement) -> str:
    lyric = corpus.lyric_at(arrangement.voice, arrangement.bars[0])
    return f"{lyric.id}:{placement.token.index}"


def _locator_word_id(corpus, arrangement: Arrangement, placement) -> str:
    return corpus.lyric_at(arrangement.voice, arrangement.bars[0]).id

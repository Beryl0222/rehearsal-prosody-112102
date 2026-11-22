"""把曲词、读音选择与拍位谱拼成一份可试唱的词格安排。

排布规则：
1. 标点切出的换气小句优先对应同一小节；小句数与小节数一致时逐小节落字。
2. 每个音节必须落在 can_start=True 的拍位；剩余拍位为该音节的拉长覆盖，
   一个字可覆盖多拍；两个音节挤同一不可拆音位即 UNSLOTTABLE，不可采用。
3. 记录词界、重音、入声以及合法/被阻断的换气点。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import issues
from .models import (
    Arrangement,
    BreathGroup,
    Issue,
    LyricRecord,
    Placement,
    Reading,
)
from .phonology import default_reading_syllables, is_entering, stressed_index

# 否定词：其后若被换气断开，否定作用域被割裂
NEGATORS = {"不", "没", "没有", "莫", "勿", "别", "无", "非"}


@dataclass
class BreathDirective:
    """换气意见对排布的约束。"""

    blocked_after_token: tuple[str, ...] = ()   # 这些词之后禁止换气（原文字符下标）
    quote_spans: tuple[tuple[int, int], ...] = ()  # 完整引语的下标闭区间，引语后允许换气


@dataclass
class BuildResult:
    arrangement: Arrangement | None
    issues: tuple[Issue, ...]
    # token 下标 -> 起始拍位，供合唱对齐与分谱标注使用
    first_beat: dict[int, str]


def _units_for_group(group: BreathGroup, chosen: dict[str, Reading]) -> list[dict]:
    """把小句展开为待排布单元。

    命中读音词条的连续字合并为一个词条单元（音节数可与字数不同），
    其余字按字面一单元一音节。返回 [{tokens, syllables, reading, word_surface}]。
    """

    units: list[dict] = []
    tokens = group.tokens
    i = 0
    while i < len(tokens):
        matched = None
        for surface, reading in chosen.items():
            window = len(surface.replace(" ", ""))
            candidate = tokens[i:i + window]
            if not candidate:
                continue
            if "".join(t.text for t in candidate).replace(" ", "") == surface.replace(" ", ""):
                matched = (candidate, reading, surface)
                break
        if matched is not None:
            cand_tokens, reading, surface = matched
            units.append({
                "tokens": cand_tokens,
                "syllables": list(reading.syllables),
                "reading": reading,
                "word_surface": surface,
            })
            i += len(cand_tokens)
        else:
            token = tokens[i]
            units.append({
                "tokens": [token],
                "syllables": default_reading_syllables(token),
                "reading": None,
                "word_surface": token.text,
            })
            i += 1
    return units


def build_arrangement(corpus, voice: str, section: str, bars: list[int],
                      chosen: dict[str, Reading],
                      directive: BreathDirective | None = None,
                      stress_locks: dict[str, int] | None = None,
                      note_ids: tuple[str, ...] = ()) -> BuildResult:
    """构造单声部单段安排。

    chosen: 词面 -> 选定 Reading（未列词面走字面读法）。
    stress_locks: 词面 -> 必须保持的重音音节偏移（从 0 计，只约束该词
    在本段的第一次出现，见 N4“第一回”）。
    """

    directive = directive or BreathDirective()
    stress_locks = stress_locks or {}
    lyric = corpus.lyric_at(voice, bars[0])
    found: list[Issue] = []
    placements: list[Placement] = []
    word_boundaries: list[int] = []
    first_beat: dict[int, str] = {}

    # 换气小句与小节的对齐：数量一致时逐小节对应；
    # 不一致时把全部小句按顺序平铺到各小节（并给出语义提示）。
    groups = list(lyric.groups)
    aligned: dict[int, BreathGroup | None] = {bar: None for bar in bars}
    if len(groups) == len(bars):
        for bar, group in zip(bars, groups):
            aligned[bar] = group
    else:
        found.append(issues.warning(
            issues.GROUP_BAR_MISMATCH,
            f"{voice} {section}：换气小句 {len(groups)} 个与小节 {len(bars)} 个不一致，"
            "改用连续落字，换气点需教师人工确认。",
            voices=(voice,), section=section, bars=tuple(bars), note_ids=note_ids,
        ))

    pending_groups = list(groups)
    for bar in bars:
        startable = corpus.startable_beats(voice, bar)
        if aligned[bar] is not None:
            group = aligned[bar]
        elif pending_groups:
            group = pending_groups.pop(0)
        else:
            group = None
        if group is None:
            continue

        units = _units_for_group(group, chosen)
        syllable_count = sum(len(u["syllables"]) for u in units)
        if syllable_count > len(startable):
            found.append(issues.error(
                issues.UNSLOTTABLE,
                f"{voice} 第{bar}小节：{syllable_count} 个音节但只有 "
                f"{len(startable)} 个可起音拍位（{', '.join(startable)}），"
                "两个音节会挤入不可拆单音位，该唱法不可采用。",
                voices=(voice,), section=section, bars=(bar,), note_ids=note_ids,
            ))
            return BuildResult(None, tuple(found), {})

        cursor = 0
        unit_first_indices: list[int] = []
        locked_seen: set[str] = set()
        for unit in units:
            reading: Reading | None = unit["reading"]
            syllables = unit["syllables"]
            stress_idx = stressed_index(reading, len(syllables))
            surface = unit["word_surface"]
            unit_first_indices.append(unit["tokens"][0].index)

            # 重音锁：已约定词面第一次出现的重音音节偏移不得被新读法移动
            if surface in stress_locks and surface not in locked_seen:
                locked_seen.add(surface)
                if reading is not None and stress_idx != stress_locks[surface]:
                    found.append(issues.error(
                        issues.STRESS_LOCK,
                        f"{voice} 第{bar}小节『{surface}』：已约定保留原重音"
                        f"（第 {stress_locks[surface] + 1} 音节），新唱法重音在第 "
                        f"{stress_idx + 1} 音节，重音被移动，该读法不可采用。",
                        voices=(voice,), section=section, bars=(bar,), note_ids=note_ids,
                    ))

            for offset, syllable in enumerate(syllables):
                beat = startable[cursor]
                cursor += 1
                placement = Placement(
                    token=unit["tokens"][min(offset, len(unit["tokens"]) - 1)],
                    syllable=syllable,
                    beat=beat,
                    bar=bar,
                    stress=(offset == stress_idx),
                    reading_id=reading.id if reading else None,
                    word_surface=unit["word_surface"],
                    entering=is_entering(syllable),
                )
                placements.append(placement)
                if offset == 0:
                    first_beat[unit["tokens"][0].index] = beat
        word_boundaries.extend(unit_first_indices)

    if not placements:
        found.append(issues.error(
            issues.UNSLOTTABLE,
            f"{voice} {section}：没有任何音节成功落拍。",
            voices=(voice,), section=section, bars=tuple(bars), note_ids=note_ids,
        ))
        return BuildResult(None, tuple(found), {})

    legal_breaths, blocked_breaths, negation_issues = _breath_points(
        corpus, voice, section, bars, lyric, placements, first_beat, directive, note_ids
    )
    found.extend(negation_issues)

    reading_id = next((r.id for r in chosen.values()), "DEFAULT")
    region = next((r.region for r in chosen.values()), None)
    arrangement = Arrangement(
        voice=voice,
        section=section,
        bars=list(bars),
        reading_id=reading_id,
        region=region,
        placements=placements,
        word_boundaries=sorted(set(word_boundaries)),
        legal_breaths=legal_breaths,
        blocked_breaths=blocked_breaths,
    )
    return BuildResult(arrangement, tuple(found), first_beat)


def _breath_points(corpus, voice, section, bars, lyric: LyricRecord,
                   placements: list[Placement], first_beat: dict[int, str],
                   directive: BreathDirective, note_ids) -> tuple[list, list, list]:
    legal: list[tuple[str, str]] = []
    blocked: list[tuple[str, str]] = []
    found: list[Issue] = []

    by_index = {p.token.index: p for p in placements}
    # 小句之间（标点处）是默认可换气点，落在前一字的拍位之后
    for group in lyric.groups:
        if group.after_punct is None:
            continue
        last_token = group.tokens[-1]
        placement = by_index.get(last_token.index)
        if placement is None or placement.bar not in bars:
            continue
        beat_text = f"{placement.beat} 之后"
        if last_token.index in directive.blocked_after_token:
            blocked.append((beat_text, f"『{last_token.text}』后换气被意见禁止（否定作用域）"))
            continue
        legal.append((beat_text, f"小句『{_group_text(group)}』后的标点换气"))

    # 否定作用域：否定词与被修饰词之间任何换气都会改变听众理解
    tokens = lyric.tokens
    for pos, token in enumerate(tokens[:-1]):
        if token.text not in NEGATORS:
            continue
        next_token = tokens[pos + 1]
        p1, p2 = by_index.get(token.index), by_index.get(next_token.index)
        if p1 is None or p2 is None:
            continue
        if token.index in directive.blocked_after_token:
            beat_text = f"{p1.beat} 之后"
            blocked.append((beat_text,
                            f"否定词『{token.text}』与『{next_token.text}』之间不可换气"))
        found.append(issues.warning(
            issues.NEGATION_SCOPE,
            f"{voice} 第{p1.bar}小节：否定词『{token.text}』修饰『{next_token.text}』，"
            f"若在 {p1.beat} 后换气会把否定与被修饰词隔开、改变听众理解；"
            "换气应挪到整个否定结构之后。",
            voices=(voice,), section=section, bars=(p1.bar,), note_ids=note_ids,
        ))

    # 引语更正：完整引语之后新增一个合法换气点
    for start, end in directive.quote_spans:
        last = lyric.token_at(end)
        if last is not None and last.index in by_index:
            p = by_index[last.index]
            legal.append((f"{p.beat} 之后", f"人物引语『{_span_text(lyric, start, end)}』结束后换气"))

    # 去重并保序
    legal = _dedupe(legal)
    blocked = _dedupe(blocked)
    return legal, blocked, found


def _group_text(group: BreathGroup) -> str:
    return "".join(t.text for t in group.tokens)


def _span_text(lyric: LyricRecord, start: int, end: int) -> str:
    return "".join(t.text for t in lyric.tokens if start <= t.index <= end)


def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

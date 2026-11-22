"""把 notes.json 的自由文本排练意见解析为结构化 Opinion。

采用显式中文规则匹配（无外部 NLP 依赖）。先把一条笔记按逗号/分号/句号
切成小句，再逐句识别段落与动作，避免“同条笔记谈两段”时张冠李戴。
没有命中任何规则的笔记保留为 UNKNOWN，绝不静默丢弃，交回教师确认。
意见按 at（提交时间）保序，后到的更正由此覆盖早先选择。
"""

from __future__ import annotations

import re

from .models import Action, Opinion, Reading

_CLAUSE_SPLIT = re.compile(r"[，。；;]")
_NEGATION_HINT = "不要在"
_QUOTE_HINT = "引语"
_REGION_HINTS = ("甲调", "乙调")
# 教师口语段落名 -> 总谱段落名
_SECTION_ALIASES = {
    "答句": "问答",
    "问句": "问答",
    "答语": "问答",
}


class NoteParser:
    def __init__(self, readings: list[Reading], sections: list[str]):
        self.readings = readings
        self.sections = sorted(sections, key=len, reverse=True)
        self.surfaces = sorted({r.surface for r in readings}, key=len, reverse=True)
        self.regions = sorted({r.region for r in readings}, key=len, reverse=True)
        # 跨笔记上下文：(声部, 段落) -> 最近讨论的词条，处理省略词条的更正句
        self._last_surface: dict[tuple[str | None, str | None], str] = {}

    # ------------------------------------------------------------ 入口
    def parse_all(self, notes: list[dict]) -> list[Opinion]:
        opinions: list[Opinion] = []
        for row in sorted(notes, key=lambda r: r["at"]):
            row_opinions = self.parse_row(row)
            for opinion in row_opinions:
                if opinion.action == Action.TRY:
                    self._last_surface[(opinion.voice, opinion.section)] = opinion.surface
                    self._last_surface[(opinion.voice, None)] = opinion.surface
            opinions.extend(row_opinions)
        return opinions

    def parse_row(self, row: dict) -> list[Opinion]:
        text = row["text"]
        base = dict(note_id=row["id"], at=row["at"], teacher=row["teacher"],
                    voice=row.get("voice"), raw=text)
        found: list[Opinion] = []
        clauses = [c.strip() for c in _CLAUSE_SPLIT.split(text) if c.strip()]
        # 预扫描段落提及跨度，用于省略主语的后续小句补挂
        section_spans: dict[str, list[int]] = {}
        for idx, clause in enumerate(clauses):
            for section in self._sections_in(clause):
                section_spans.setdefault(section, [idx, idx])[1] = idx

        inherited_section = None
        # 唱法意见可能先出现、段落后出现（“『那厢』用甲调，前句和问答都可试”），
        # 暂存待决意见，等读到段落小句再落地
        pending: list[Opinion] = []
        for idx, clause in enumerate(clauses):
            mentioned = self._sections_in(clause)
            if mentioned:
                inherited_section = mentioned[-1]
            current_section = mentioned[-1] if mentioned else inherited_section
            targets = mentioned or ([current_section] if current_section else [])

            if not targets:
                # 段落无法判定：TRY 暂存等待后续段落小句，其余意见原样保留
                for opinion in self._parse_clause(clause, None, base, text):
                    if opinion.action == Action.TRY:
                        pending.append(opinion)
                    else:
                        found.append(opinion)
                continue

            for target in targets:
                clause_opinions = self._parse_clause(clause, target, base, text)
                found.extend(clause_opinions)
                landed_keys = {
                    (o.action, o.surface, o.region) for o in clause_opinions
                }
                for opinion in pending:
                    key = (opinion.action, opinion.surface, opinion.region)
                    if key not in landed_keys:
                        found.append(Opinion(
                            **{k: v for k, v in opinion.__dict__.items()
                               if k != "section"},
                            section=target,
                        ))
            pending.clear()
            # 省略主语的后续句：落在某段提及跨度内则补挂
            for name, span in section_spans.items():
                if name in targets:
                    continue
                if span[0] <= idx <= span[1]:
                    found.extend(self._parse_clause(clause, name, base, text))
            # 本句有唱法但无段落：留待后续段落小句
            if not mentioned and any(
                self._region_for(s, clause) for s in self._surfaces_in(clause)
            ):
                for opinion in self._parse_clause(clause, None, base, text):
                    if opinion.action == Action.TRY:
                        pending.append(opinion)
        # 收尾仍未落地的待决意见保留空段落，由教师在 check 输出中人工确认
        found.extend(pending)

        if row.get("approval"):
            sections = self._sections_in(text) or [None]
            for section in sections:
                found.append(Opinion(**base, action=Action.APPROVE, section=section,
                                     detail="分排确认回执（不代表合唱总排确认）"))

        if not found:
            found.append(Opinion(**base, action=Action.UNKNOWN,
                                 detail="未匹配任何解析规则，需教师人工确认"))
        return self._dedupe(found)

    @staticmethod
    def _dedupe(opinions: list[Opinion]) -> list[Opinion]:
        seen: set[tuple] = set()
        out: list[Opinion] = []
        for opinion in opinions:
            key = (opinion.action, opinion.section, opinion.surface,
                   opinion.region, opinion.note_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(opinion)
        return out

    # ------------------------------------------------------------ 小句规则
    def _parse_clause(self, clause: str, section: str | None, base: dict,
                      full_text: str = "") -> list[Opinion]:
        out: list[Opinion] = []

        # 1) 引语更正：『X』是人物引语
        if _QUOTE_HINT in clause:
            match = re.search(r"『(?P<word>[^』]+)』是人物引语", clause)
            if match:
                out.append(Opinion(
                    **base, action=Action.QUOTE, section=section,
                    surface=match.group("word"),
                    detail=f"『{match.group('word')}』为完整人物引语，换气挪到引语后",
                ))

        # 2) 禁止换气（否定作用域）
        if _NEGATION_HINT in clause:
            match = re.search(r"不要在『(?P<word>[^』]+)』后", clause)
            word = match.group("word") if match else None
            out.append(Opinion(
                **base, action=Action.AVOID_BREATH, section=section, surface=word,
                detail=f"禁止在『{word}』后换气（否定作用域）",
            ))

        # 3) 保留重音
        if "保留原来重音" in clause:
            for surface in self._surfaces_in(clause):
                out.append(Opinion(
                    **base, action=Action.KEEP_STRESS, section=section, surface=surface,
                    detail="保留原重音（第一次出现）",
                ))

        # 4) 唱法选择/更正：句中同时出现词条与地区唱法；
        #    省略词条时（“问答改试乙调”）依次用本句前缀、跨笔记上下文补全。
        surfaces = self._surfaces_in(clause)
        if not surfaces:
            prefix = full_text[: full_text.find(clause)] if clause in full_text else ""
            for surface in self.surfaces:
                if surface in prefix:
                    surfaces.append(surface)
                    break
        if not surfaces:
            voice = base.get("voice")
            fallback = self._last_surface.get((voice, section))
            if fallback is None:
                fallback = self._last_surface.get((voice, None))
            if fallback is not None:
                surfaces.append(fallback)
        for surface in surfaces:
            region = self._region_for(surface, clause)
            if region is not None:
                out.append(Opinion(
                    **base, action=Action.TRY, section=section,
                    surface=surface, region=region,
                    detail=f"{surface} 试 {region}",
                ))
        return out

    # ------------------------------------------------------------ 工具
    def _surfaces_in(self, text: str) -> list[str]:
        return [s for s in self.surfaces if s in text]

    def _sections_in(self, text: str) -> list[str]:
        hits = [s for s in self.sections if s in text]
        for alias, canonical in _SECTION_ALIASES.items():
            if alias in text and canonical not in hits:
                hits.append(canonical)
        return hits

    def _region_for(self, surface: str, text: str) -> str | None:
        candidates = {r.region for r in self.readings if r.surface == surface}
        for region in self.regions:
            short = region[-2:] if region.endswith(_REGION_HINTS) else region
            if region in text or short in text:
                if region in candidates:
                    return region
        return None

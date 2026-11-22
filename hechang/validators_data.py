"""原始交换资料的完整性校验。

加载阶段只做宽容解析；这里显式检查字段、跨表关联与取值范围，
问题以 ValueError 列出，便于把错误资料原样退回。
"""

from __future__ import annotations


class DataValidationError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("；".join(problems))
        self.problems = problems


def validate_tables(score_rows: list[dict], word_rows: list[dict],
                    note_rows: list[dict]) -> list[str]:
    problems: list[str] = []

    def require(row: dict, fields: tuple[str, ...], table: str, row_id: str):
        for field in fields:
            if field not in row:
                problems.append(f"{table} {row_id} 缺少字段 {field}")

    score_ids: set[str] = set()
    staff: set[tuple[str, int]] = set()
    for row in score_rows:
        rid = row.get("id", "?")
        require(row, ("id", "bar", "section", "voice", "slots", "shared"),
                "score", rid)
        if rid in score_ids:
            problems.append(f"score 出现重复 id：{rid}")
        score_ids.add(rid)
        staff.add((row.get("voice"), row.get("bar")))
        beats = {s.get("beat") for s in row.get("slots", [])}
        for name, shared_beats in row.get("shared", {}).items():
            for beat in shared_beats:
                if beat not in beats:
                    problems.append(
                        f"score {rid} 的共享标记『{name}』引用了不存在的拍位 {beat}"
                    )

    word_ids: set[str] = set()
    pronunciation_surfaces: set[str] = set()
    for row in word_rows:
        rid = row.get("id", "?")
        require(row, ("id",), "words", rid)
        if rid in word_ids:
            problems.append(f"words 出现重复 id：{rid}")
        word_ids.add(rid)
        if row.get("kind") == "pronunciation":
            require(row, ("surface", "region", "syllables", "stress"),
                    "words", rid)
            syllables = row.get("syllables", [])
            stress = row.get("stress")
            if not isinstance(syllables, list) or not syllables:
                problems.append(f"words {rid} 的 syllables 必须是非空数组")
            elif not isinstance(stress, int) or not 1 <= stress <= len(syllables):
                problems.append(
                    f"words {rid} 的 stress={stress} 超出音节范围 1..{len(syllables)}"
                )
            pronunciation_surfaces.add(row.get("surface"))
        else:
            require(row, ("voice", "bars", "text"), "words", rid)
            for bar in row.get("bars", []):
                if (row.get("voice"), bar) not in staff:
                    problems.append(
                        f"words {rid} 引用了谱面中不存在的声部/小节："
                        f"{row.get('voice')} 第{bar}小节"
                    )

    note_ids: set[str] = set()
    for row in note_rows:
        rid = row.get("id", "?")
        require(row, ("id", "at", "teacher", "text"), "notes", rid)
        if rid in note_ids:
            problems.append(f"notes 出现重复 id：{rid}")
        note_ids.add(rid)
        if not isinstance(row.get("at"), int):
            problems.append(f"notes {rid} 的 at 必须是整数时间序号")

    return problems


def assert_valid(score_rows, word_rows, note_rows) -> None:
    problems = validate_tables(score_rows, word_rows, note_rows)
    if problems:
        raise DataValidationError(problems)

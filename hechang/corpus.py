"""加载 data/ 三份交换表并建立索引；解决“同词多次出现”的辨认问题。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .models import Occurrence, Reading, ScoreBar, Slot
from .phonology import build_lyric_record
from .models import LyricRecord


class Corpus:
    """一次排练的全部原始材料，按声部/小节/字词建立索引。"""

    def __init__(self, score_rows: list[dict], word_rows: list[dict], note_rows: list[dict]):
        self.bars: list[ScoreBar] = []
        self._bar_index: dict[tuple[str, int], ScoreBar] = {}
        for row in score_rows:
            bar = ScoreBar(
                id=row["id"],
                bar=row["bar"],
                section=row["section"],
                voice=row["voice"],
                slots=[Slot(s["beat"], s["can_start"]) for s in row["slots"]],
                shared={k: list(v) for k, v in row.get("shared", {}).items()},
            )
            self.bars.append(bar)
            self._bar_index[(bar.voice, bar.bar)] = bar

        self.lyrics: list[LyricRecord] = []
        self.readings: list[Reading] = []
        for row in word_rows:
            if row.get("kind") == "pronunciation":
                self.readings.append(
                    Reading(
                        id=row["id"],
                        surface=row["surface"],
                        region=row["region"],
                        syllables=tuple(row["syllables"]),
                        stress=row["stress"],
                    )
                )
            else:
                self.lyrics.append(build_lyric_record(row))

        self.notes: list[dict] = list(note_rows)
        self.voices = sorted({bar.voice for bar in self.bars})
        self.sections: dict[str, list[int]] = {}
        for bar in self.bars:
            self.sections.setdefault(bar.section, [])
            if bar.bar not in self.sections[bar.section]:
                self.sections[bar.section].append(bar.bar)
        for key in self.sections:
            self.sections[key].sort()

        self._lyric_index: dict[tuple[str, int], LyricRecord] = {}
        for lyric in self.lyrics:
            for bar in lyric.bars:
                self._lyric_index[(lyric.voice, bar)] = lyric
        self._occurrence_counter: dict[tuple[str, str], int] = defaultdict(int)

    # ------------------------------------------------------------ 构造
    @classmethod
    def load(cls, data_dir: str | Path) -> "Corpus":
        from .validators_data import assert_valid

        data_dir = Path(data_dir)
        score_rows = json.loads((data_dir / "score.json").read_text(encoding="utf-8"))
        word_rows = json.loads((data_dir / "words.json").read_text(encoding="utf-8"))
        note_rows = json.loads((data_dir / "notes.json").read_text(encoding="utf-8"))
        assert_valid(score_rows, word_rows, note_rows)
        return cls(score_rows, word_rows, note_rows)

    # ------------------------------------------------------------ 查谱
    def score_bar(self, voice: str, bar: int) -> ScoreBar:
        return self._bar_index[(voice, bar)]

    def startable_beats(self, voice: str, bar: int) -> list[str]:
        return [s.beat for s in self.score_bar(voice, bar).slots if s.can_start]

    def all_beats(self, voice: str, bar: int) -> list[str]:
        return [s.beat for s in self.score_bar(voice, bar).slots]

    def section_of(self, voice: str, bar: int) -> str:
        return self.score_bar(voice, bar).section

    def bars_for_voice(self, voice: str) -> list[int]:
        return sorted(bar.bar for bar in self.bars if bar.voice == voice)

    def voices_in_section(self, section: str) -> list[str]:
        return sorted({b.voice for b in self.bars if b.section == section})

    def is_shared_section(self, section: str) -> bool:
        return len(self.voices_in_section(section)) > 1

    # ------------------------------------------------------------ 查词
    def lyric_at(self, voice: str, bar: int) -> LyricRecord:
        return self._lyric_index[(voice, bar)]

    def find_reading(self, reading_id: str) -> Reading:
        for reading in self.readings:
            if reading.id == reading_id:
                return reading
        raise KeyError(f"读音词条不存在: {reading_id}")

    def readings_for_surface(self, surface: str) -> list[Reading]:
        return [r for r in self.readings if r.surface == surface]

    def region_reading(self, surface: str, region: str) -> Reading:
        for reading in self.readings_for_surface(surface):
            if reading.region == region:
                return reading
        raise KeyError(f"词条 {surface} 没有 {region} 读法")

    def find_occurrences(self, surface: str, voice: OptionalFilter = None,
                         section: OptionalFilter = None) -> list[Occurrence]:
        """辨认一个字词“是哪一次”出现：声部 + 小节范围 + 所在小句。"""

        results: list[Occurrence] = []
        seen_counter: dict[tuple[str, str], int] = defaultdict(int)
        for lyric in self.lyrics:
            if voice is not None and lyric.voice != voice:
                continue
            for match in self._match_surface(lyric, surface):
                indices, start, end = match
                bars = tuple(bar for bar in lyric.bars
                             if self._bar_index[(lyric.voice, bar)].section == section) \
                    if section else tuple(lyric.bars)
                if section is not None and not bars:
                    continue
                bar_range = bars if bars else tuple(lyric.bars)
                sec = section or self._bar_index[(lyric.voice, lyric.bars[0])].section
                # 序号在同一曲词记录内计次：不同记录各自从 1 开始
                seen_counter[(lyric.id, surface)] += 1
                context = self._context_group(lyric, indices)
                results.append(Occurrence(
                    word_id=lyric.id,
                    voice=lyric.voice,
                    bars=bar_range,
                    section=sec,
                    surface=surface,
                    indices=tuple(indices),
                    ordinal=seen_counter[(lyric.id, surface)],
                    context=context,
                ))
        return results

    def _match_surface(self, lyric: LyricRecord,
                       surface: str) -> list[tuple[list[int], int, int]]:
        """在曲词里匹配字面。

        拉丁词条（如 ``hold on``）本身是一个 Token；多字条目按连续 Token
        窗口匹配，窗口内 Token 拼接等于词条即命中，返回字符下标序列。
        """

        from .phonology import tokenize

        tokens = lyric.tokens
        compact = surface.replace(" ", "")
        window = len(tokenize(surface))
        out: list[tuple[list[int], int, int]] = []
        for pos in range(0, max(0, len(tokens) - window + 1)):
            window_tokens = tokens[pos:pos + window]
            if "".join(t.text for t in window_tokens).replace(" ", "") != compact:
                continue
            indices = [t.index for t in window_tokens]
            out.append((indices, indices[0], indices[-1]))
        return out

    def _context_group(self, lyric: LyricRecord, indices: set[int] | tuple[int, ...]) -> str:
        index_set = set(indices)
        for group in lyric.groups:
            group_indices = {t.index for t in group.tokens}
            if index_set & group_indices:
                return "".join(t.text for t in group.tokens)
        return lyric.text

    # ------------------------------------------------------------ 合唱标记
    def shared_marks(self, section: str) -> dict[str, dict[str, list[str]]]:
        """段内所有共享标记：标记名 -> 声部 -> 拍位列表（只保留多声部共有的标记）。"""

        marks: dict[str, dict[str, list[str]]] = defaultdict(dict)
        for bar in self.bars:
            if bar.section != section:
                continue
            for name, beats in bar.shared.items():
                marks[name].setdefault(bar.voice, [])
                for beat in beats:
                    if beat not in marks[name][bar.voice]:
                        marks[name][bar.voice].append(beat)
        return {name: voices for name, voices in marks.items() if len(voices) > 1}

    def solo_marks(self, voice: str, section: str) -> dict[str, list[str]]:
        marks: dict[str, list] = defaultdict(list)
        for bar in self.bars:
            if bar.section == section and bar.voice == voice:
                for name, beats in bar.shared.items():
                    for beat in beats:
                        if beat not in marks[name]:
                            marks[name].append(beat)
        return dict(marks)


OptionalFilter = "str | None"

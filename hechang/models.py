"""领域模型：对应 data/ 三份交换表以及派生出的试唱安排。

所有记录保留原始 id，便于从分谱回溯原词、原意见。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------- 谱面拍位


@dataclass(frozen=True)
class Slot:
    """单个拍位。can_start=False 表示不可拆单音位，不能承载新音节。"""

    beat: str
    can_start: bool


@dataclass
class ScoreBar:
    """score.json 的一行：某声部某小节的拍位与合唱标记。"""

    id: str
    bar: int
    section: str
    voice: str
    slots: list[Slot]
    # 标记名 -> 该小节内参与标记的拍位
    shared: dict[str, list[str]] = field(default_factory=dict)

    def slot(self, beat: str) -> Optional[Slot]:
        for slot in self.slots:
            if slot.beat == beat:
                return slot
        return None


# ---------------------------------------------------------------- 曲词切分


@dataclass(frozen=True)
class Token:
    """曲词中的一个可唱单元（汉字或拉丁词），标点不产生 Token。"""

    text: str
    index: int          # 在所属 words 记录内的字符下标，用于回溯原词
    is_latin: bool


@dataclass(frozen=True)
class BreathGroup:
    """按标点（逗号/句号）切出的语义小句，换气默认落在组间。"""

    tokens: list[Token]
    after_punct: Optional[str]
    start_index: int
    end_index: int      # 最后一个 token 的字符下标


@dataclass
class LyricRecord:
    """words.json 中 kind 缺失的一行：某声部跨若干小节的曲词。"""

    id: str
    voice: str
    bars: list[int]
    text: str
    groups: list[BreathGroup] = field(default_factory=list)

    @property
    def tokens(self) -> list[Token]:
        return [token for group in self.groups for token in group.tokens]

    def token_at(self, index: int) -> Optional[Token]:
        for token in self.tokens:
            if token.index == index:
                return token
        return None


@dataclass(frozen=True)
class Reading:
    """words.json 中 kind=pronunciation 的一行：一种地区唱法。"""

    id: str
    surface: str
    region: str
    syllables: tuple[str, ...]
    stress: int                 # 从 1 计的重音音节序号

    @property
    def entering(self) -> bool:
        """入声：最后一个音节以塞音尾 p/t/k 收束（hiap 或 hia-p 两种记法）。"""

        last = self.syllables[-1]
        if last.endswith(("-p", "-t", "-k")):
            return True
        return len(last) > 1 and last[-1] in "ptk" and last[-2] in "aeiouy"


# ---------------------------------------------------------------- 分排意见


class Action(str, enum.Enum):
    """意见类型。UNKNOWN 表示规则未能解析，原文保留供人工查看。"""

    TRY = "try"                       # 某声部某段试某唱法
    AVOID_BREATH = "avoid_breath"     # 禁止在某词后换气（语义作用域）
    APPROVE = "approve"               # 分排确认回执
    KEEP_STRESS = "keep_stress"       # 指定片段保留原重音、不换到别处
    QUOTE = "quote"                   # 更正：某两字是完整人物引语
    UNKNOWN = "unknown"


@dataclass
class Opinion:
    """从 notes.json 一行文本解析出的结构化意见（可能一行多条）。"""

    note_id: str
    at: int
    teacher: str
    voice: Optional[str]
    action: Action
    section: Optional[str] = None
    surface: Optional[str] = None
    region: Optional[str] = None
    approval: bool = False
    raw: str = ""
    detail: str = ""


# ---------------------------------------------------------------- 出现辨认


@dataclass(frozen=True)
class Occurrence:
    """同一字词在曲词中的“某一次”出现：靠声部+小节范围+前后句辨认。"""

    word_id: str
    voice: str
    bars: tuple[int, ...]
    section: str
    surface: str
    indices: tuple[int, ...]          # 在该 LyricRecord 中的字符下标
    ordinal: int                      # 同一声部内第几次出现（从 1 计）
    context: str                      # 所在小句原文，便于人工核对


# ---------------------------------------------------------------- 试唱安排


@dataclass(frozen=True)
class Placement:
    """一个音节落到某拍位的具体安排。"""

    token: Token
    syllable: str
    beat: str
    bar: int
    stress: bool                      # 是否为该读法的重音音节
    reading_id: Optional[str]         # 命中读音词条时记录，否则为 None
    word_surface: Optional[str]       # 所属多字词面，用于词界展示
    entering: bool = False


@dataclass
class Arrangement:
    """某声部、某段（跨若干小节）在选定唱法下的完整词格安排。"""

    voice: str
    section: str
    bars: list[int]
    reading_id: str                   # 主读音选择（甲调/乙调…）；无词条时为 "DEFAULT"
    region: Optional[str]
    placements: list[Placement] = field(default_factory=list)
    word_boundaries: list[int] = field(default_factory=list)  # 词界处的 token 下标
    legal_breaths: list[tuple[str, str]] = field(default_factory=list)  # (拍位, 说明)
    blocked_breaths: list[tuple[str, str]] = field(default_factory=list)

    def placements_in_bar(self, bar: int) -> list[Placement]:
        return [p for p in self.placements if p.bar == bar]


# ---------------------------------------------------------------- 校验与方案


class IssueLevel(str, enum.Enum):
    ERROR = "error"       # 不能联合试唱
    WARNING = "warning"   # 语义风险，需教师知情


@dataclass(frozen=True)
class Issue:
    code: str
    level: IssueLevel
    voices: tuple[str, ...]
    section: Optional[str]
    bars: tuple[int, ...]
    message: str
    note_ids: tuple[str, ...] = ()


class SegmentStatus(str, enum.Enum):
    CONFIRMED = "已确认"            # 分排确认且当前仍合法
    TRIAL = "试唱"                  # 有新唱法选择，可试唱但未确认
    BLOCKED = "待声部确认"          # 共享落点不兼容，退回相关声部
    PRACTICABLE = "可继续练"        # 无联合方案，但原有合法段落保留


@dataclass(frozen=True)
class SegmentVerdict:
    voice: Optional[str]             # None 表示两声部联合结论
    section: str
    bars: tuple[int, ...]
    status: SegmentStatus
    reading_id: Optional[str]
    region: Optional[str]
    issues: tuple[Issue, ...]
    note_ids: tuple[str, ...]
    arrangement: Optional[Arrangement]
    message: str = ""


@dataclass(frozen=True)
class Alternative:
    """未达成一致的备选唱法及冲突原因，供教师回看。"""

    section: str
    bars: tuple[int, ...]
    voice: str
    reading_id: str
    region: str
    rejected_for: tuple[str, ...]    # Issue.code 列表
    note_ids: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """负责人选定的一份联合试唱方案；所有分谱对应同一次选择。"""

    selection_id: str
    created_from_notes: tuple[int, ...]
    usable: bool
    verdicts: tuple[SegmentVerdict, ...]
    alternatives: tuple[Alternative, ...]
    issues: tuple[Issue, ...]
    arrangements: tuple[Arrangement, ...]
    practice_ready_sections: tuple[str, ...]   # 已确认且仍合法、可发学员的段

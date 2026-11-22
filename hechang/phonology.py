"""读音与音节：切字、声母落点、入声、重音。

音节采用轻量记音串：可选声母（拉丁辅音串）+ 元音 + 可选韵尾；
入声以 -p/-t/-k 韵尾标注（例如 ``hiap`` 写作 ``hia-p``）。
不依赖任何外部读音数据库，只用 words.json 里的词条。
"""

from __future__ import annotations

import re
from typing import Optional

from .models import BreathGroup, LyricRecord, Reading, Token

_VOWELS = set("aeiouy")
# 入声韵尾：塞音 p/t/k。记音串可写 hia-p，也可直接写 hiap
_ENTERING_FINALS = "ptk"
_LATIN_WORD = re.compile(r"[A-Za-z]+(?:\s+[A-Za-z]+)*")
# 只把拉丁字母串当作外来词；汉字逐字成 Token
_PUNCT = set("，。！？；：、,.!?;:")


def onset(syllable: str) -> str:
    """取音节的声母（辅音落点）。零声母返回空串。"""

    head = []
    for ch in syllable:
        if ch in _VOWELS:
            break
        head.append(ch)
    return "".join(head)


def landing(syllable: str) -> str:
    """辅音落点：有声母记为声母，零声母记为 ∅。"""

    return onset(syllable) or "∅"


def is_entering(syllable: str) -> bool:
    if syllable.endswith(("-p", "-t", "-k")):
        return True
    # 无连字符形式（hiap、thit）：末位是塞音且前一位是元音
    return (
        len(syllable) > 1
        and syllable[-1] in _ENTERING_FINALS
        and syllable[-2] in _VOWELS
    )


# ---------------------------------------------------------------- 曲词切分


def tokenize(text: str) -> list[Token]:
    """把曲词原文切成可唱 Token，标点跳过但字符下标保留。"""

    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace() or ch in _PUNCT:
            i += 1
            continue
        if ("a" <= ch.lower() <= "z"):
            match = _LATIN_WORD.match(text, i)
            assert match is not None
            word = match.group(0)
            tokens.append(Token(text=word, index=i, is_latin=True))
            i = match.end()
        else:
            tokens.append(Token(text=ch, index=i, is_latin=False))
            i += 1
    return tokens


def split_groups(text: str) -> list[BreathGroup]:
    """按标点切语义小句（换气组），记录组后标点。"""

    tokens = tokenize(text)
    groups: list[BreathGroup] = []
    current: list[Token] = []
    for token in tokens:
        current.append(token)
        # 看 token 与下一个 token 之间是否有标点
        gap = text[token.index + len(token.text):]
        next_idx = _next_token_index(text, token.index + len(token.text))
        punct = _punct_between(text, token.index + len(token.text), next_idx)
        if punct:
            groups.append(
                BreathGroup(
                    tokens=list(current),
                    after_punct=punct,
                    start_index=current[0].index,
                    end_index=token.index,
                )
            )
            current = []
    if current:
        groups.append(
            BreathGroup(
                tokens=list(current),
                after_punct=None,
                start_index=current[0].index,
                end_index=current[-1].index,
            )
        )
    return groups


def _next_token_index(text: str, start: int) -> int:
    i = start
    while i < len(text) and (text[i].isspace() or text[i] in _PUNCT):
        i += 1
    return i


def _punct_between(text: str, start: int, end: int) -> Optional[str]:
    for ch in text[start:end]:
        if ch in _PUNCT:
            return ch
    return None


def build_lyric_record(row: dict) -> LyricRecord:
    record = LyricRecord(
        id=row["id"], voice=row["voice"], bars=list(row["bars"]), text=row["text"]
    )
    record.groups = split_groups(record.text)
    return record


# ---------------------------------------------------------------- 读音选择


def reading_for(reading: Reading, surface_token_count: int) -> list[str]:
    """展开一个读音的音节串。词条音节数可与字面字数不同（如那厢→niang）。"""

    return list(reading.syllables)


def default_reading_syllables(token: Token) -> list[str]:
    """无词条时的字面读法：每个汉字/拉丁词各占一个音节，重音在首音节。"""

    if token.is_latin:
        return [part for part in token.text.split()]
    return [token.text]


def stressed_index(reading: Optional[Reading], syllable_count: int) -> int:
    """重音音节下标（从 0 计）。无词条时首音节重读。"""

    if reading is None:
        return 0
    return max(0, min(reading.stress - 1, syllable_count - 1))

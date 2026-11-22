"""联合校验：入声/共有尾音/换气重入对齐，以及独唱段弹性检查。

输入是各声部在同一候选唱法下的 Arrangement；输出 Issue 列表。
共享段的标记取两声部的交集：交集中的拍点必须在同一小节、同拍对上，
且该拍点确实承载对应性质的音节（收音=段内该字最后音节，重入=换气后第一音节）。
"""

from __future__ import annotations

from . import issues
from .models import Arrangement, Issue, Placement


def _placement_at(arrangement: Arrangement, bar: int, beat: str) -> Placement | None:
    for placement in arrangement.placements:
        if placement.bar == bar and placement.beat == beat:
            return placement
    return None


def _bar_of_beat(beat: str) -> int:
    return int(beat.split(":", 1)[0])


def validate_shared_marks(corpus, section: str,
                          arrangements: dict[str, Arrangement]) -> list[Issue]:
    """校验共享段的共有尾音、换气重入等标记。"""

    found: list[Issue] = []
    marks = corpus.shared_marks(section)
    voices = sorted(arrangements)
    for name, per_voice in marks.items():
        common_beats = None
        for voice in voices:
            beats = set(per_voice.get(voice, []))
            common_beats = beats if common_beats is None else common_beats & beats
        common_beats = common_beats or set()

        for beat in sorted(common_beats, key=_beat_sort_key):
            bar = _bar_of_beat(beat)
            placed = {v: _placement_at(arrangements[v], bar, beat) for v in voices}
            missing = [v for v in voices if placed[v] is None]
            if missing:
                found.append(issues.error(
                    issues.MARK_NO_PLACEMENT,
                    f"{section} 第{bar}小节 {beat} 的『{name}』要求 {('、'.join(voices))} 共同执行，"
                    f"但 {('、'.join(missing))} 该拍没有起音音节。",
                    voices=tuple(missing), section=section, bars=(bar,),
                ))
                continue

            if name == "共同收音":
                issue = _check_coda(section, beat, bar, placed, arrangements)
            elif name == "换气重入":
                issue = _check_reentry(section, beat, bar, placed)
            else:
                issue = _check_generic_landing(section, name, beat, bar, placed)
            if issue is not None:
                found.append(issue)
    return found


def _check_coda(section, beat, bar, placed: dict[str, Placement],
                arrangements: dict[str, Arrangement]) -> Issue | None:
    words = {p.word_surface for p in placed.values()}
    landings = {p.syllable for p in placed.values()}
    # 每个声部在该小节的最后一个落字必须就在共同收音拍
    for voice, placement in placed.items():
        in_bar = [p for p in arrangements[voice].placements if p.bar == bar]
        if in_bar and in_bar[-1].beat != beat:
            return issues.error(
                issues.CODA_MISMATCH,
                f"{section} 第{bar}小节 {beat} 标记『共同收音』，但 {voice} 的小节末字落在 "
                f"{in_bar[-1].beat}（{in_bar[-1].word_surface}），共有尾音对不上。",
                voices=tuple(sorted(placed)), section=section, bars=(bar,),
            )
    if len(words) > 1 or len(landings) > 1:
        return issues.error(
            issues.CODA_MISMATCH,
            f"{section} 第{bar}小节 {beat} 的共有尾音落在不同字/音节上："
            + "；".join(f"{v} 收在 {p.word_surface}/{p.syllable}" for v, p in sorted(placed.items())),
            voices=tuple(sorted(placed)), section=section, bars=(bar,),
        )
    return None


def _check_reentry(section, beat, bar, placed: dict[str, Placement]) -> Issue | None:
    # 换气后再进入：两声部该拍必须都有起音，且声母落点一致
    landings = {}
    for voice, placement in placed.items():
        from .phonology import landing
        landings[voice] = landing(placement.syllable)
    if len(set(landings.values())) > 1:
        return issues.error(
            issues.REENTRY_MISMATCH,
            f"{section} 第{bar}小节 {beat} 的『换气重入』要求同拍再进入，但辅音落点不同："
            + "；".join(f"{v}={landings[v]}" for v in sorted(landings)),
            voices=tuple(sorted(placed)), section=section, bars=(bar,),
        )
    return None


def _check_generic_landing(section, name, beat, bar, placed) -> Issue | None:
    from .phonology import landing
    landings = {v: landing(p.syllable) for v, p in placed.items()}
    if len(set(landings.values())) > 1:
        return issues.error(
            issues.REENTRY_MISMATCH,
            f"{section} 第{bar}小节 {beat} 的『{name}』要求共同落点，实际："
            + "；".join(f"{v}={landings[v]}" for v in sorted(landings)),
            voices=tuple(sorted(placed)), section=section, bars=(bar,),
        )
    return None


def validate_solo_marks(corpus, voice: str, section: str,
                        arrangement: Arrangement) -> list[Issue]:
    """独唱段：标记拍位只要求本声部有落字；弹性空间由教师保留，不做硬对齐。"""

    found: list[Issue] = []
    for name, beats in corpus.solo_marks(voice, section).items():
        # 独唱段里出现的共享标记不与其他声部交集，仅校验本拍可唱
        for beat in beats:
            bar = _bar_of_beat(beat)
            if _placement_at(arrangement, bar, beat) is None:
                found.append(issues.warning(
                    issues.MARK_NO_PLACEMENT,
                    f"{voice} {section} 第{bar}小节 {beat} 的『{name}』没有落字，"
                    "独唱可自行处理弹性，但需在分谱上注明。",
                    voices=(voice,), section=section, bars=(bar,),
                ))
    return found


def validate_entering_alignment(corpus, section: str,
                                arrangements: dict[str, Arrangement]) -> list[Issue]:
    """入声字在共享段必须同拍收短：标出各声部入声落点供教师核对。"""

    found: list[Issue] = []
    by_beat: dict[tuple[int, str], dict[str, Placement]] = {}
    for voice, arrangement in arrangements.items():
        for placement in arrangement.placements:
            if placement.entering:
                by_beat.setdefault((placement.bar, placement.beat), {})[voice] = placement
    for (bar, beat), per_voice in sorted(by_beat.items(), key=lambda kv: _beat_sort_key(kv[0][1])):
        if len(per_voice) != len(arrangements):
            continue  # 只有一个声部唱入声，不构成共享冲突
        from .phonology import landing
        landings = {v: landing(p.syllable) for v, p in per_voice.items()}
        if len(set(landings.values())) > 1:
            found.append(issues.error(
                issues.REENTRY_MISMATCH,
                f"{section} 第{bar}小节 {beat} 的入声收短落点不一致："
                + "；".join(f"{v}={landings[v]}" for v in sorted(landings)),
                voices=tuple(sorted(per_voice)), section=section, bars=(bar,),
            ))
    return found


def _beat_sort_key(beat: str):
    bar, _, rest = beat.partition(":")
    sub = 0
    if rest.endswith("+"):
        sub = 1
        rest = rest[:-1]
    return (int(bar), int(rest), sub)

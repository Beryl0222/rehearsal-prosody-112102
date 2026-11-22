"""规划引擎：从原始材料与分排意见推出可联合试唱的方案。

关键纪律：
- 分排确认只约束本声部；共享段一位教师接受新读音，不代表其他声部已接受
  随之移动的入声/收音/重入，必须重新做联合校验。
- 共享落点无法兼容时退回相关声部一起确认（BLOCKED），原来已确认且仍合法
  的整段继续练，已认可的其他段照常发给学员。
- 每个候选都保留冲突明细与备选；最终方案只有一份选择，分谱全部对它生成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from . import issues
from .models import (
    Alternative,
    Arrangement,
    Action,
    Issue,
    IssueLevel,
    Opinion,
    Plan,
    Reading,
    SegmentStatus,
    SegmentVerdict,
)
from .notes import NoteParser
from .rhythm import BreathDirective, build_arrangement
from .validation import (
    validate_entering_alignment,
    validate_shared_marks,
    validate_solo_marks,
)


@dataclass
class SectionCandidate:
    voice: str
    section: str
    bars: tuple[int, ...]
    reading: Reading
    note_ids: tuple[str, ...]
    overrides: dict[str, Reading] = field(default_factory=dict)


class Planner:
    def __init__(self, corpus):
        self.corpus = corpus
        self.parser = NoteParser(corpus.readings, list(corpus.sections))
        self.opinions: list[Opinion] = []
        self._baseline: dict[tuple[str, str], Arrangement] = {}
        self._baseline_first_beat: dict[tuple[str, str], dict[int, str]] = {}
        self._baseline_failures: dict[tuple[str, str], tuple[Issue, ...]] = {}

    # ============================================================== 主入口
    def make_plan(self, selection_seq: int = 2) -> Plan:
        self.opinions = self.parser.parse_all(self.corpus.notes)
        self._build_baselines()
        verdicts: list[SegmentVerdict] = []
        alternatives: list[Alternative] = []
        all_issues: list[Issue] = []
        chosen_arrangements: list[Arrangement] = []
        practice_ready: list[str] = []

        for section, bars in self.corpus.sections.items():
            bars = tuple(bars)
            voices = self.corpus.voices_in_section(section)
            shared = self.corpus.is_shared_section(section)
            note_ids = tuple(sorted({
                o.note_id for o in self.opinions if o.section == section
            }))

            if shared:
                verdict, section_alts, section_issues, arrangements = self._shared_section(
                    section, bars, voices, note_ids
                )
            else:
                verdict, section_alts, section_issues, arrangements = self._solo_section(
                    section, bars, voices, note_ids
                )
            verdicts.append(verdict)
            alternatives.extend(section_alts)
            all_issues.extend(section_issues)
            chosen_arrangements.extend(arrangements)
            if verdict.status in (SegmentStatus.CONFIRMED, SegmentStatus.PRACTICABLE):
                practice_ready.append(section)

        unknown = [o for o in self.opinions if o.action == Action.UNKNOWN]
        for opinion in unknown:
            all_issues.append(issues.warning(
                issues.READING_UNKNOWN,
                f"笔记 {opinion.note_id} 未能解析为可执行安排：{opinion.raw}",
                voices=(opinion.voice,) if opinion.voice else (),
                note_ids=(opinion.note_id,),
            ))

        blocking_codes = {
            issues.UNSLOTTABLE, issues.CODA_MISMATCH, issues.REENTRY_MISMATCH,
            issues.STRESS_LOCK, issues.SECTION_BLOCKED,
        }
        usable = not any(
            i.level == IssueLevel.ERROR and i.code in blocking_codes for i in all_issues
        )
        plan = Plan(
            selection_id=f"SEL-{selection_seq}",
            created_from_notes=tuple(sorted({o.at for o in self.opinions})),
            usable=usable,
            verdicts=tuple(verdicts),
            alternatives=tuple(alternatives),
            issues=tuple(all_issues),
            arrangements=tuple(chosen_arrangements),
            practice_ready_sections=tuple(dict.fromkeys(practice_ready)),
        )
        return plan

    # ============================================================== 基线
    def _build_baselines(self) -> None:
        """基线安排：所有词走字面读法（无方言选择），用于重音锁与更正追溯。

        基线本身也可能落不下（例如可起音拍位不足），失败原因留痕，不抛异常。
        """

        for voice in self.corpus.voices:
            for section, bars in self.corpus.sections.items():
                if voice not in self.corpus.voices_in_section(section):
                    continue
                result = build_arrangement(
                    self.corpus, voice, section, list(bars), chosen={},
                    directive=BreathDirective(), note_ids=(),
                )
                if result.arrangement is not None:
                    self._baseline[(voice, section)] = result.arrangement
                    self._baseline_first_beat[(voice, section)] = result.first_beat
                else:
                    self._baseline_failures[(voice, section)] = result.issues

    # ============================================================== 独唱段
    def _solo_section(self, section, bars, voices, note_ids):
        voice = voices[0]
        candidates = self._candidates(voice, section)
        section_issues: list[Issue] = []
        section_alts: list[Alternative] = []
        arrangements: list[Arrangement] = []
        baseline = self._baseline.get((voice, section))

        if not candidates:
            if baseline is None:
                fail = self._baseline_failures.get((voice, section), ())
                verdict = SegmentVerdict(
                    voice=voice, section=section, bars=bars,
                    status=SegmentStatus.BLOCKED, reading_id=None, region=None,
                    issues=fail, note_ids=note_ids, arrangement=None,
                    message="字面读法也无法落拍，问题交回老师。",
                )
                section_issues.extend(fail)
                return verdict, section_alts, section_issues, arrangements
            approved = self._is_approved(voice, section)
            status = SegmentStatus.CONFIRMED if approved else SegmentStatus.TRIAL
            verdict = SegmentVerdict(
                voice=voice, section=section, bars=bars, status=status,
                reading_id=baseline.reading_id, region=None, issues=(),
                note_ids=note_ids, arrangement=baseline,
                message="照原样（字面读法）；独唱保留弹性空间。",
            )
            arrangements.append(baseline)
            return verdict, section_alts, section_issues, arrangements

        # 独唱段：逐候选检查，取最新意见对应的唱法
        best = candidates[-1]
        directive = self._directive(voice, section)
        result = build_arrangement(
            self.corpus, voice, section, list(bars), chosen=best.overrides,
            directive=directive, note_ids=best.note_ids,
        )
        section_issues.extend(result.issues)
        if result.arrangement is None or any(
            i.level == IssueLevel.ERROR for i in result.issues
        ):
            for candidate in candidates:
                section_alts.append(self._alternative(
                    candidate, [i.code for i in result.issues]
                ))
            if baseline is not None:
                verdict = SegmentVerdict(
                    voice=voice, section=section, bars=bars,
                    status=SegmentStatus.PRACTICABLE, reading_id=baseline.reading_id,
                    region=None, issues=tuple(result.issues), note_ids=note_ids,
                    arrangement=baseline,
                    message="新唱法不可采用，回到已排练的原词格继续练。",
                )
                arrangements.append(baseline)
            else:
                verdict = SegmentVerdict(
                    voice=voice, section=section, bars=bars,
                    status=SegmentStatus.BLOCKED, reading_id=None, region=None,
                    issues=tuple(result.issues), note_ids=note_ids, arrangement=None,
                    message="新唱法不可采用且无合法原词格，问题交回老师。",
                )
            return verdict, section_alts, section_issues, arrangements

        approved = self._is_approved(voice, section)
        status = SegmentStatus.CONFIRMED if approved else SegmentStatus.TRIAL
        verdict = SegmentVerdict(
            voice=voice, section=section, bars=bars, status=status,
            reading_id=best.reading.id, region=best.reading.region,
            issues=tuple(result.issues), note_ids=note_ids,
            arrangement=result.arrangement,
            message="独唱段，教师可保留弹性处理。",
        )
        arrangements.append(result.arrangement)
        for candidate in candidates[:-1]:
            section_alts.append(Alternative(
                section=section, bars=bars, voice=voice,
                reading_id=candidate.reading.id, region=candidate.reading.region,
                rejected_for=("SUPERSEDED",), note_ids=candidate.note_ids,
            ))
        return verdict, section_alts, section_issues, arrangements

    # ============================================================== 共享段
    def _shared_section(self, section, bars, voices, note_ids):
        section_issues: list[Issue] = []
        section_alts: list[Alternative] = []
        directives = {v: self._directive(v, section) for v in voices}
        locks = {v: self._stress_locks(v, section) for v in voices}

        # 每个声部的可选唱法：时间线上的候选 + 字面基线（若基线可落拍）
        options_by_voice: dict[str, list[SectionCandidate]] = {}
        for voice in voices:
            options = list(self._candidates(voice, section))
            if (voice, section) in self._baseline:
                options.append(self._baseline_candidate(voice, section, bars))
            if not options:
                # 连基线都落不下：放一个空候选，评估时给出基线失败原因
                options.append(self._baseline_candidate(voice, section, bars))
            options_by_voice[voice] = options

        # 评估单个候选：返回安排（合法时）与全部问题
        def evaluate(voice: str, candidate: SectionCandidate):
            if not candidate.overrides and (voice, section) in self._baseline_failures:
                return None, list(self._baseline_failures[(voice, section)])
            result = build_arrangement(
                self.corpus, voice, section, list(bars),
                chosen=candidate.overrides, directive=directives[voice],
                stress_locks=locks[voice], note_ids=candidate.note_ids,
            )
            local_errors = [i for i in result.issues if i.level == IssueLevel.ERROR]
            if result.arrangement is None or local_errors:
                return None, list(result.issues)
            return result.arrangement, list(result.issues)

        # 枚举全部联合组合，记录每个候选被否决的具体原因
        rejection_codes: dict[tuple[str, str], set[str]] = {}
        legal_combos: list[tuple[int, dict[str, Arrangement], list[Issue]]] = []
        latest_index = {v: len(options_by_voice[v]) - 1 for v in voices}

        for combo in product(*(options_by_voice[v] for v in voices)):
            per_voice = dict(zip(voices, combo))
            arrangements: dict[str, Arrangement] = {}
            combo_issues: list[Issue] = []
            combo_failed = False
            for voice, candidate in per_voice.items():
                arrangement, local_issues = evaluate(voice, candidate)
                combo_issues.extend(local_issues)
                key = (voice, candidate.reading.id)
                if arrangement is None:
                    combo_failed = True
                    for issue in local_issues:
                        if issue.level == IssueLevel.ERROR:
                            rejection_codes.setdefault(key, set()).add(issue.code)
                else:
                    arrangements[voice] = arrangement

            joint_issues: list[Issue] = []
            if not combo_failed and len(arrangements) == len(voices):
                joint_issues.extend(validate_shared_marks(
                    self.corpus, section, arrangements
                ))
                joint_issues.extend(validate_entering_alignment(
                    self.corpus, section, arrangements
                ))
                for voice in voices:
                    joint_issues.extend(validate_solo_marks(
                        self.corpus, voice, section, arrangements[voice]
                    ))
                combo_issues.extend(joint_issues)
                joint_errors = [i for i in joint_issues if i.level == IssueLevel.ERROR]
                if not joint_errors:
                    # 合法度：越接近各声部最新候选，排名越前
                    score = sum(
                        options_by_voice[v].index(per_voice[v]) - latest_index[v]
                        for v in voices
                    )
                    legal_combos.append((score, arrangements, combo_issues))
                else:
                    for issue in joint_errors:
                        for voice in voices:
                            if voice in issue.voices or not issue.voices:
                                key = (voice, per_voice[voice].reading.id)
                                rejection_codes.setdefault(key, set()).add(issue.code)

        all_approved = all(self._is_approved(v, section) for v in voices)

        if legal_combos:
            legal_combos.sort(key=lambda item: item[0])
            _, arrangements, combo_issues = legal_combos[0]
            section_issues.extend(combo_issues)
            chosen_readings = {
                v: next(c for c in options_by_voice[v]
                        if c.reading.id == self._reading_id_of(arrangements[v]))
                for v in voices
            }
            status = SegmentStatus.CONFIRMED if all_approved else SegmentStatus.TRIAL
            reading_ids = {c.reading.id for c in chosen_readings.values()}
            regions = {c.reading.region for c in chosen_readings.values()}
            verdict = SegmentVerdict(
                voice=None, section=section, bars=bars, status=status,
                reading_id="/".join(sorted(reading_ids)),
                region="/".join(sorted(r for r in regions if r)),
                issues=tuple(i for i in combo_issues if i.level != IssueLevel.ERROR),
                note_ids=note_ids, arrangement=None,
                message=("各声部分排均已确认，联合校验通过。" if all_approved
                         else "联合可试唱，待相关声部共同确认新落点。"),
            )
            for voice, options in options_by_voice.items():
                chosen = chosen_readings[voice]
                for candidate in options:
                    if candidate.reading.id == chosen.reading.id:
                        continue
                    codes = rejection_codes.get((voice, candidate.reading.id), set())
                    section_alts.append(self._alternative(
                        candidate, sorted(codes) or ["NOT_JOINTLY_SELECTED"]
                    ))
            return verdict, section_alts, section_issues, list(arrangements.values())

        # 没有任何联合合法组合：把问题交回老师，说明具体冲突在哪几句
        latest_combo = {v: options_by_voice[v][-1] for v in voices}
        fatal_issues: list[Issue] = []
        warning_issues: list[Issue] = []
        for voice, candidate in latest_combo.items():
            _, local_issues = evaluate(voice, candidate)
            fatal_issues.extend(i for i in local_issues if i.level == IssueLevel.ERROR)
            warning_issues.extend(i for i in local_issues if i.level == IssueLevel.WARNING)
        # 再补一轮最新组合的联合校验问题
        partial: dict[str, Arrangement] = {}
        for voice, candidate in latest_combo.items():
            arrangement, _ = evaluate(voice, candidate)
            if arrangement is not None:
                partial[voice] = arrangement
        if len(partial) == len(voices):
            fatal_issues.extend(i for i in validate_shared_marks(
                self.corpus, section, partial
            ) if i.level == IssueLevel.ERROR)
        section_issues.extend(fatal_issues)

        # 仍合法的基线可继续练（仅当各声部基线都能独立落拍）
        baseline_arrangements = {
            v: self._baseline[(v, section)] for v in voices
            if (v, section) in self._baseline
        }
        baseline_legal = (
            len(baseline_arrangements) == len(voices)
            and not validate_shared_marks(self.corpus, section, baseline_arrangements)
        )
        status = SegmentStatus.PRACTICABLE if baseline_legal else SegmentStatus.BLOCKED
        blocked_issue = issues.error(
            issues.SECTION_BLOCKED,
            f"{section}（小节 {_bars_text(bars)}）找不到共同唱法："
            + "；".join(i.message for i in fatal_issues)
            + "。共享落点无法兼容，退回相关声部一起确认。",
            voices=tuple(voices), section=section, bars=bars, note_ids=note_ids,
        )
        section_issues.append(blocked_issue)
        section_issues.extend(warning_issues)
        verdict = SegmentVerdict(
            voice=None, section=section, bars=bars, status=status,
            reading_id=None, region=None,
            issues=tuple([blocked_issue, *fatal_issues, *warning_issues]),
            note_ids=note_ids, arrangement=None,
            message=("共享落点无法兼容，退回相关声部一起确认；"
                     "原已确认且仍合法的词格可继续练。" if baseline_legal
                     else "原词格同样不满足合唱标记，需教师重排；"
                          "已认可的其他段依然可发给学员。"),
        )
        for voice, options in options_by_voice.items():
            for candidate in options:
                codes = rejection_codes.get((voice, candidate.reading.id), set())
                if codes:
                    section_alts.append(self._alternative(candidate, sorted(codes)))
        keep = list(baseline_arrangements.values()) if baseline_legal else []
        return verdict, section_alts, section_issues, keep

    @staticmethod
    def _reading_id_of(arrangement: Arrangement) -> str:
        return arrangement.reading_id

    # ============================================================== 候选与指令
    def _candidates(self, voice: str, section: str) -> list[SectionCandidate]:
        """按时间线收集某声部某段的唱法候选（后到更正排在最后）。

        同一读法被多条笔记重复提及时合并为一个候选，保留全部笔记 id。
        笔记未写段落时，若该声部只出现在一个段，则归入该段。
        """

        voice_sections = {
            b.section for b in self.corpus.bars if b.voice == voice
        }
        implicit_section = next(iter(voice_sections)) if len(voice_sections) == 1 else None
        out: list[SectionCandidate] = []
        index_by_reading: dict[str, int] = {}
        for opinion in self.opinions:
            if opinion.action != Action.TRY or opinion.voice != voice:
                continue
            target_section = opinion.section or implicit_section
            if target_section != section or not opinion.surface:
                continue
            reading = self.corpus.region_reading(opinion.surface, opinion.region)
            overrides = self._overrides_with_dependencies(voice, section, reading)
            if reading.id in index_by_reading:
                existing = out[index_by_reading[reading.id]]
                existing.note_ids = tuple(dict.fromkeys(
                    [*existing.note_ids, opinion.note_id]
                ))
            else:
                index_by_reading[reading.id] = len(out)
                out.append(SectionCandidate(
                    voice=voice, section=section,
                    bars=tuple(self.corpus.sections[section]),
                    reading=reading, note_ids=(opinion.note_id,), overrides=overrides,
                ))
        return out

    def _overrides_with_dependencies(self, voice, section, reading: Reading) -> dict[str, Reading]:
        """一个段内若有多条唱法意见，候选保留同段其他词面的最新选择。"""

        overrides: dict[str, Reading] = {}
        for opinion in self.opinions:
            if (opinion.action == Action.TRY and opinion.voice == voice
                    and opinion.section == section and opinion.surface):
                overrides[opinion.surface] = self.corpus.region_reading(
                    opinion.surface, opinion.region
                )
        overrides[reading.surface] = reading
        return overrides

    def _baseline_candidate(self, voice, section, bars) -> SectionCandidate:
        default = Reading(id="DEFAULT", surface="(字面)", region="",
                          syllables=(), stress=1)
        return SectionCandidate(
            voice=voice, section=section, bars=bars, reading=default,
            note_ids=(), overrides={},
        )

    def _implicit_section(self, voice: str) -> str | None:
        """笔记未写段落时，声部只属于一个段则隐式归入该段。"""

        voice_sections = {b.section for b in self.corpus.bars if b.voice == voice}
        return next(iter(voice_sections)) if len(voice_sections) == 1 else None

    def _directive(self, voice: str, section: str) -> BreathDirective:
        implicit = self._implicit_section(voice)
        blocked: list[str] = []
        quotes: list[tuple[int, int]] = []
        for opinion in self.opinions:
            if opinion.voice != voice:
                continue
            if (opinion.section or implicit) != section:
                continue
            if opinion.action == Action.AVOID_BREATH and opinion.surface:
                for occurrence in self.corpus.find_occurrences(
                    opinion.surface, voice=voice, section=section
                ):
                    blocked.append(occurrence.indices[-1])
            if opinion.action == Action.QUOTE and opinion.surface:
                for occurrence in self.corpus.find_occurrences(
                    opinion.surface, voice=voice, section=section
                ):
                    quotes.append((occurrence.indices[0], occurrence.indices[-1]))
        return BreathDirective(
            blocked_after_token=tuple(sorted(set(blocked))),
            quote_spans=tuple(quotes),
        )

    def _stress_locks(self, voice: str, section: str) -> dict[str, int]:
        """KEEP_STRESS：锁的是词内重音音节偏移（从 0 计），只约束第一次出现。

        偏移从基线词格里该词第一次出现的重音位置取；基线落不下时，
        用该词字面切分的首音节重音作为约定值。
        """

        locks: dict[str, int] = {}
        implicit = self._implicit_section(voice)
        for opinion in self.opinions:
            if (opinion.action != Action.KEEP_STRESS or opinion.voice != voice
                    or (opinion.section or implicit) != section
                    or not opinion.surface):
                continue
            surface = opinion.surface
            baseline = self._baseline.get((voice, section))
            offset = None
            if baseline is not None:
                seen: set[str] = set()
                for placement in baseline.placements:
                    if placement.word_surface != surface:
                        continue
                    if surface in seen:
                        break
                    if placement.stress:
                        # 在该词所属音节串中的偏移：同词面连续落字计数
                        same_word = [p for p in baseline.placements
                                     if p.word_surface == surface]
                        offset = same_word.index(placement) % max(1, len(same_word))
                        break
                    seen.add(surface)
            if offset is None:
                offset = 0
            locks[surface] = offset
        return locks

    def _is_approved(self, voice: str, section: str) -> bool:
        """分排确认回执：只代表本声部，且不含针对该段的后续更正。"""

        implicit = self._implicit_section(voice)
        approve_ats = [o.at for o in self.opinions
                       if o.action == Action.APPROVE and o.voice == voice
                       and (o.section == section
                            or o.section is None and implicit == section
                            or o.section is None and implicit is None)]
        if not approve_ats:
            return False
        last_approval = max(approve_ats)
        later_change = [o for o in self.opinions
                        if o.voice == voice
                        and (o.section or implicit) == section
                        and o.at > last_approval
                        and o.action in (Action.TRY, Action.QUOTE)]
        return not later_change

    def _alternative(self, candidate: SectionCandidate, codes: list[str]) -> Alternative:
        return Alternative(
            section=candidate.section, bars=candidate.bars, voice=candidate.voice,
            reading_id=candidate.reading.id, region=candidate.reading.region,
            rejected_for=tuple(sorted(set(c for c in codes if c))),
            note_ids=candidate.note_ids,
        )

    # ============================================================== 更正追溯
    def trace_correction(self, plan: Plan, note_id: str) -> dict:
        """后来的引语/改读更正：从原词定位需重练的位置，区分已排练与新安排。"""

        opinion = next((o for o in self.opinions if o.note_id == note_id), None)
        if opinion is None:
            raise KeyError(f"找不到笔记 {note_id}")
        blocked_sections = {
            v.section for v in plan.verdicts
            if v.status == SegmentStatus.BLOCKED
        }
        items = []
        for occurrence in self.corpus.find_occurrences(
            opinion.surface or "", voice=opinion.voice, section=opinion.section
        ):
            baseline_failure = self._baseline_failures.get(
                (occurrence.voice, occurrence.section)
            )
            old_beat = self._baseline_first_beat.get(
                (occurrence.voice, occurrence.section), {}
            ).get(occurrence.indices[0])
            new_arrangement = next(
                (a for a in plan.arrangements
                 if a.voice == occurrence.voice and a.section == occurrence.section),
                None,
            )
            new_beat = None
            if new_arrangement is not None:
                new_beat = next(
                    (p.beat for p in new_arrangement.placements
                     if p.token.index == occurrence.indices[0]),
                    None,
                )
            section_blocked = occurrence.section in blocked_sections
            if section_blocked:
                status = "blocked"
                repractice = False
            elif old_beat is None and baseline_failure:
                status = "no_baseline"
                repractice = new_beat is not None
            else:
                status = "mapped"
                repractice = old_beat != new_beat
            items.append({
                "word_id": occurrence.word_id,
                "section": occurrence.section,
                "bars": list(occurrence.bars),
                "ordinal": occurrence.ordinal,
                "context": occurrence.context,
                "indices": list(occurrence.indices),
                "rehearsed_beat": old_beat,
                "new_beat": new_beat,
                "repractice": repractice,
                "status": status,
            })
        return {
            "note_id": note_id,
            "action": opinion.action.value,
            "surface": opinion.surface,
            "voice": opinion.voice,
            "selection_id": plan.selection_id,
            "items": items,
        }


def _bars_text(bars: tuple[int, ...]) -> str:
    return "、".join(str(b) for b in bars)

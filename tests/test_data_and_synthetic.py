"""数据校验、未知笔记保留与合成语料场景。"""

import copy
import unittest

from hechang.corpus import Corpus
from hechang.models import Action, SegmentStatus
from hechang.notes import NoteParser
from hechang.planner import Planner
from hechang.rhythm import BreathDirective, build_arrangement
from hechang.validators_data import DataValidationError, validate_tables
from tests._base import DATA_DIR


def _load_raw():
    import json
    return {
        name: json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("score", "words", "notes")
    }


class DataValidationTest(unittest.TestCase):
    def test_given_data_is_valid(self):
        raw = _load_raw()
        self.assertEqual(
            validate_tables(raw["score"], raw["words"], raw["notes"]), []
        )

    def test_missing_field_and_bad_reference_reported(self):
        raw = _load_raw()
        score = copy.deepcopy(raw["score"])
        del score[0]["slots"]
        words = copy.deepcopy(raw["words"])
        words.append({"id": "BX", "voice": "高声", "bars": [99], "text": "悬空"})
        problems = validate_tables(score, words, raw["notes"])
        self.assertTrue(any("slots" in p for p in problems))
        self.assertTrue(any("BX" in p and "99" in p for p in problems))
        with self.assertRaises(DataValidationError):
            # 经 load 同款校验入口；直接构造 Corpus 不重复校验
            from hechang.validators_data import assert_valid
            assert_valid(score, words, raw["notes"])

    def test_stress_out_of_range_reported(self):
        raw = _load_raw()
        words = copy.deepcopy(raw["words"])
        words[4]["stress"] = 9
        problems = validate_tables(raw["score"], words, raw["notes"])
        self.assertTrue(any("stress" in p for p in problems))

    def test_shared_beat_must_exist(self):
        raw = _load_raw()
        score = copy.deepcopy(raw["score"])
        score[1]["shared"]["共同收音"].append("8:9")
        problems = validate_tables(score, raw["words"], raw["notes"])
        self.assertTrue(any("8:9" in p for p in problems))


class UnknownNoteTest(unittest.TestCase):
    def test_unparseable_note_kept_as_unknown(self):
        corpus = Corpus.load(DATA_DIR)
        notes = corpus.notes + [{
            "id": "NX", "at": 99, "teacher": "江老师", "voice": "高声",
            "text": "今天天气不错，大家加油。",
        }]
        opinions = NoteParser(corpus.readings, list(corpus.sections)).parse_all(notes)
        unknown = [o for o in opinions if o.note_id == "NX"]
        self.assertTrue(unknown)
        self.assertEqual(unknown[0].action, Action.UNKNOWN)
        # 原文必须保留，不能静默丢弃
        self.assertIn("天气", unknown[0].raw)


class SyntheticCorpusTest(unittest.TestCase):
    """最小合成语料：验证入声同拍收短与可联合方案的完整链路。"""

    def _build(self):
        score = [
            {"id": "S1", "bar": 1, "section": "合", "voice": "高",
             "slots": [{"beat": "1:1", "can_start": True},
                       {"beat": "1:2", "can_start": True}],
             "shared": {"共同收音": ["1:2"]}},
            {"id": "S2", "bar": 1, "section": "合", "voice": "低",
             "slots": [{"beat": "1:1", "can_start": True},
                       {"beat": "1:2", "can_start": True}],
             "shared": {"共同收音": ["1:2"]}},
        ]
        words = [
            {"id": "L1", "voice": "高", "bars": [1], "text": "甲叶"},
            {"id": "L2", "voice": "低", "bars": [1], "text": "甲叶"},
            {"id": "P1", "kind": "pronunciation", "surface": "叶",
             "region": "入声调", "syllables": ["hiap"], "stress": 1},
        ]
        notes = [
            {"id": "M1", "at": 1, "teacher": "师", "voice": "高",
             "text": "『叶』用入声调。"},
            {"id": "M2", "at": 2, "teacher": "师", "voice": "低",
             "text": "『叶』用入声调。"},
        ]
        return Corpus(score, words, notes)

    def test_entering_syllable_marked_and_jointly_singable(self):
        corpus = self._build()
        plan = Planner(corpus).make_plan()
        self.assertTrue(plan.usable)
        verdict = plan.verdicts[0]
        self.assertEqual(verdict.section, "合")
        self.assertIn(verdict.status,
                      (SegmentStatus.TRIAL, SegmentStatus.CONFIRMED))
        for arrangement in plan.arrangements:
            last = arrangement.placements[-1]
            self.assertTrue(last.entering)
            self.assertEqual(last.beat, "1:2")

    def test_entering_mismatch_detected_when_beats_differ(self):
        corpus = self._build()
        reading = corpus.find_reading("P1")
        high = build_arrangement(
            corpus, "高", "合", [1], {"叶": reading}
        ).arrangement
        low = build_arrangement(
            corpus, "低", "合", [1], {"叶": reading}
        ).arrangement
        # 同构数据下校验通过
        from hechang.validation import validate_shared_marks
        self.assertEqual(
            validate_shared_marks(corpus, "合", {"高": high, "低": low}), []
        )


class BreathDirectiveTest(unittest.TestCase):
    def test_directive_carries_blocked_tokens_and_quotes(self):
        corpus = Corpus.load(DATA_DIR)
        planner = Planner(corpus)
        planner.opinions = planner.parser.parse_all(corpus.notes)
        directive = planner._directive("高声", "问答")
        # 莫（W2 下标 0）之后禁止换气；莫唱（0,1）是完整引语
        self.assertIn(0, directive.blocked_after_token)
        self.assertIn((0, 1), directive.quote_spans)


if __name__ == "__main__":
    unittest.main()

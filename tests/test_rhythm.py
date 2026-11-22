"""拍位排布：不可拆音位、拉长覆盖、词界、重音锁与换气作用域。"""

from hechang.corpus import Corpus
from hechang.models import IssueLevel
from hechang.rhythm import BreathDirective, build_arrangement
from tests._base import DATA_DIR, CorpusCase


class ArrangementTest(CorpusCase):
    def test_syllable_cannot_share_unsplittable_slot(self):
        # 低声第 8 小节只有两个可起音拍位，字面“山那厢”3 音节 -> 不可采用
        result = build_arrangement(
            self.corpus, "低声", "问答", [8, 9], chosen={}
        )
        self.assertIsNone(result.arrangement)
        codes = {i.code for i in result.issues}
        self.assertIn("UNSLOTTABLE", codes)
        issue = next(i for i in result.issues if i.code == "UNSLOTTABLE")
        self.assertEqual(issue.level, IssueLevel.ERROR)
        self.assertIn("不可拆单音位", issue.message)

    def test_one_syllable_word_frees_slot_for_low_voice(self):
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        result = build_arrangement(
            self.corpus, "低声", "问答", [8, 9], chosen={"那厢": yi}
        )
        self.assertIsNotNone(result.arrangement)
        bar8 = result.arrangement.placements_in_bar(8)
        self.assertEqual([p.beat for p in bar8], ["8:1", "8:4"])
        self.assertEqual([p.syllable for p in bar8], ["山", "niang"])

    def test_long_syllable_covers_multiple_beats(self):
        # 一个字拉长覆盖多拍：7:4 的 xiang 之后没有新起音，允许占满到小节末
        jia = self.corpus.region_reading("那厢", "青岸甲调")
        result = build_arrangement(
            self.corpus, "高声", "前句", [7], chosen={"那厢": jia}
        )
        beats = [p.beat for p in result.arrangement.placements]
        self.assertEqual(beats, ["7:1", "7:3", "7:4"])
        # 7:2 不可起音，没有任何音节落在那里
        self.assertNotIn("7:2", beats)

    def test_word_boundaries_recorded(self):
        jia = self.corpus.region_reading("那厢", "青岸甲调")
        result = build_arrangement(
            self.corpus, "高声", "前句", [7], chosen={"那厢": jia}
        )
        lyric = self.corpus.lyric_at("高声", 7)
        # 词界落在每个词第一个字的字符下标
        first_indices = {lyric.tokens[0].index, lyric.tokens[1].index}
        self.assertTrue(set(result.arrangement.word_boundaries) <= first_indices)

    def test_negation_scope_warns_and_blocks_breath(self):
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        directive = self.planner._directive("高声", "问答")
        result = build_arrangement(
            self.corpus, "高声", "问答", [8, 9],
            chosen={"那厢": yi}, directive=directive,
        )
        warnings_ = [i for i in result.issues if i.code == "NEGATION_SCOPE"]
        self.assertTrue(warnings_)
        self.assertIn("否定", warnings_[0].message)
        blocked_text = " ".join(b for _, b in result.arrangement.blocked_breaths)
        self.assertIn("莫", blocked_text)

    def test_quote_correction_moves_legal_breath_after_quote(self):
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        directive = self.planner._directive("高声", "问答")
        result = build_arrangement(
            self.corpus, "高声", "问答", [8, 9],
            chosen={"那厢": yi}, directive=directive,
        )
        reasons = " ".join(r for _, r in result.arrangement.legal_breaths)
        self.assertIn("引语", reasons)
        self.assertIn("莫唱", reasons)

    def test_stress_lock_rejects_reading_that_moves_stress(self):
        # 高声拍位充足：锁第 1 音节重音，甲调重音在第 2 音节 -> STRESS_LOCK
        jia = self.corpus.region_reading("那厢", "青岸甲调")
        result = build_arrangement(
            self.corpus, "高声", "问答", [8, 9],
            chosen={"那厢": jia}, stress_locks={"那厢": 0},
        )
        codes = {i.code for i in result.issues}
        self.assertIn("STRESS_LOCK", codes)

    def test_stress_lock_slot_shortage_reports_unsplittable(self):
        # 低声拍位不足：字面 3 音节挤进 2 个可起音拍位
        result = build_arrangement(
            self.corpus, "低声", "问答", [8, 9], chosen={}
        )
        self.assertIsNone(result.arrangement)
        self.assertIn("UNSLOTTABLE", {i.code for i in result.issues})

    def test_stress_lock_allows_matching_reading(self):
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        result = build_arrangement(
            self.corpus, "低声", "问答", [8, 9],
            chosen={"那厢": yi}, stress_locks={"那厢": 0},
        )
        self.assertIsNotNone(result.arrangement)
        self.assertNotIn("STRESS_LOCK", {i.code for i in result.issues})


if __name__ == "__main__":
    import unittest
    unittest.main()

"""联合校验：共有尾音、换气重入、入声对齐与独唱弹性。"""

from hechang.corpus import Corpus
from hechang.rhythm import build_arrangement
from hechang.validation import (
    validate_entering_alignment,
    validate_shared_marks,
)
from tests._base import CorpusCase


class SharedMarksTest(CorpusCase):
    def _arrangements(self, high_reading, low_reading):
        chosen_high = {"那厢": high_reading} if high_reading else {}
        chosen_low = {"那厢": low_reading} if low_reading else {}
        high = build_arrangement(
            self.corpus, "高声", "问答", [8, 9], chosen=chosen_high
        ).arrangement
        low = build_arrangement(
            self.corpus, "低声", "问答", [8, 9], chosen=chosen_low
        ).arrangement
        return high, low

    def test_yidiao_pair_fails_reentry_landing(self):
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        high, low = self._arrangements(yi, yi)
        self.assertIsNotNone(high)
        self.assertIsNotNone(low)
        issues = validate_shared_marks(
            self.corpus, "问答", {"高声": high, "低声": low}
        )
        codes = {i.code for i in issues}
        # 9:2 换气重入：高声落“兄(h)”、低声落“等(d)”，辅音落点不同
        self.assertIn("REENTRY_MISMATCH", codes)
        message = " ".join(i.message for i in issues)
        self.assertIn("9:2", message)

    def test_coda_requires_last_syllable_on_shared_beat(self):
        jia = self.corpus.region_reading("那厢", "青岸甲调")
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        high, low = self._arrangements(jia, yi)
        issues = validate_shared_marks(
            self.corpus, "问答", {"高声": high, "低声": low}
        )
        coda = [i for i in issues if i.code == "CODA_MISMATCH"]
        self.assertTrue(coda)
        self.assertIn("8:4", coda[0].message)

    def test_entering_alignment_helper_accepts_same_landing(self):
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        high, low = self._arrangements(yi, yi)
        # 数据里没有入声字时，辅助校验不产生问题
        issues = validate_entering_alignment(
            self.corpus, "问答", {"高声": high, "低声": low}
        )
        self.assertEqual(issues, [])

    def test_solo_section_has_no_cross_voice_marks(self):
        # 前句只有高声，不构成跨声部共享标记
        marks = self.corpus.shared_marks("前句")
        self.assertEqual(marks, {})


if __name__ == "__main__":
    import unittest
    unittest.main()

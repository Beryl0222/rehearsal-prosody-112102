"""读音、切字、辅音落点、入声与重音。"""

import unittest

from hechang.models import Reading, Token
from hechang.phonology import (
    default_reading_syllables,
    is_entering,
    landing,
    onset,
    split_groups,
    stressed_index,
    tokenize,
)


class PhonologyTest(unittest.TestCase):
    def test_onset_and_landing(self):
        self.assertEqual(onset("na"), "n")
        self.assertEqual(onset("xiang"), "x")
        self.assertEqual(onset("niang"), "n")
        self.assertEqual(landing("a"), "∅")  # 零声母
        self.assertEqual(landing("hiang"), "h")

    def test_entering_detection(self):
        self.assertTrue(is_entering("hiap"))
        self.assertTrue(is_entering("thit"))
        self.assertFalse(is_entering("na"))

    def test_stress_index(self):
        jia = Reading(id="NY1", surface="那厢", region="甲",
                      syllables=("na", "xiang"), stress=2)
        yi = Reading(id="NY2", surface="那厢", region="乙",
                     syllables=("niang",), stress=1)
        self.assertEqual(stressed_index(jia, 2), 1)
        self.assertEqual(stressed_index(yi, 1), 0)
        self.assertEqual(stressed_index(None, 3), 0)

    def test_tokenize_keeps_indices_and_latin(self):
        tokens = tokenize("莫唱山那厢，阿兄 hold on")
        self.assertEqual([t.text for t in tokens],
                         ["莫", "唱", "山", "那", "厢", "阿", "兄", "hold on"])
        self.assertTrue(tokens[-1].is_latin)
        # 字符下标在原句中可直接定位
        self.assertEqual("莫唱山那厢，阿兄 hold on"[tokens[0].index], "莫")
        self.assertEqual("莫唱山那厢，阿兄 hold on"[tokens[-1].index], "h")

    def test_split_groups_on_punctuation(self):
        groups = split_groups("山那厢，等一等")
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].after_punct, "，")
        self.assertIsNone(groups[1].after_punct)
        self.assertEqual([t.text for t in groups[1].tokens], ["等", "一", "等"])

    def test_default_syllables(self):
        latin = Token(text="hold on", index=0, is_latin=True)
        han = Token(text="山", index=0, is_latin=False)
        self.assertEqual(default_reading_syllables(latin), ["hold", "on"])
        self.assertEqual(default_reading_syllables(han), ["山"])


if __name__ == "__main__":
    unittest.main()

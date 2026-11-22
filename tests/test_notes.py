"""分排意见解析：分句、段落别名、跨笔记省略补全、时间线覆盖。"""

import unittest

from hechang.corpus import Corpus
from hechang.models import Action
from hechang.notes import NoteParser
from tests._base import DATA_DIR


class NoteParserTest(unittest.TestCase):
    def setUp(self):
        self.corpus = Corpus.load(DATA_DIR)
        self.parser = NoteParser(self.corpus.readings, list(self.corpus.sections))
        self.opinions = self.parser.parse_all(self.corpus.notes)

    def _find(self, note_id, action):
        return [o for o in self.opinions
                if o.note_id == note_id and o.action == action]

    def test_n1_reading_covers_both_sections(self):
        tries = self._find("N1", Action.TRY)
        self.assertEqual({o.section for o in tries}, {"前句", "问答"})
        self.assertTrue(all(o.region == "青岸甲调" for o in tries))

    def test_n1_negation_breath_only_attached_to_qa(self):
        avoids = self._find("N1", Action.AVOID_BREATH)
        self.assertEqual(len(avoids), 1)
        self.assertEqual(avoids[0].section, "问答")
        self.assertEqual(avoids[0].surface, "莫")

    def test_n2_tail_sentence_kept_original_no_reading(self):
        # “尾句照原样”不产生唱法意见
        tail_tries = [o for o in self._find("N2", Action.TRY) if o.section == "尾句"]
        self.assertEqual(tail_tries, [])
        qa = self._find("N2", Action.TRY)
        self.assertEqual(len(qa), 1)
        self.assertEqual(qa[0].region, "青岸乙调")

    def test_n3_approval_scoped_to_own_voice_sections(self):
        approvals = self._find("N3", Action.APPROVE)
        self.assertEqual({o.section for o in approvals}, {"前句", "问答"})
        self.assertTrue(all(o.voice == "高声" for o in approvals))

    def test_n4_section_alias_dajv_means_qa(self):
        keeps = self._find("N4", Action.KEEP_STRESS)
        self.assertEqual(len(keeps), 1)
        self.assertEqual(keeps[0].section, "问答")
        self.assertEqual(keeps[0].surface, "那厢")
        approvals = self._find("N4", Action.APPROVE)
        self.assertEqual({o.section for o in approvals}, {"尾句", "问答"})

    def test_n5_quote_and_elided_reading_correction(self):
        quotes = self._find("N5", Action.QUOTE)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].surface, "莫唱")
        tries = self._find("N5", Action.TRY)
        # “问答改试乙调”省略词条，靠跨笔记上下文补全为“那厢”
        self.assertEqual(len(tries), 1)
        self.assertEqual(tries[0].surface, "那厢")
        self.assertEqual(tries[0].region, "青岸乙调")
        # “不动前句”：前句不出现 N5 的新唱法
        self.assertFalse(any(o.section == "前句" for o in tries))

    def test_timeline_order_preserved(self):
        ats = [o.at for o in self.opinions]
        self.assertEqual(ats, sorted(ats))

    def test_no_silent_unknown_for_given_notes(self):
        unknowns = self._find_any(Action.UNKNOWN)
        self.assertEqual(unknowns, [])

    def _find_any(self, action):
        return [o for o in self.opinions if o.action == action]


if __name__ == "__main__":
    unittest.main()

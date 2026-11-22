"""同一字词反复出现时的辨认：声部、小节范围、前后句、出现次序。"""

from tests._base import CorpusCase


class OccurrenceTest(CorpusCase):
    def test_na_xiang_occurs_in_both_voices_with_ordinal(self):
        found = self.corpus.find_occurrences("那厢")
        surfaces = {(o.voice, o.word_id, o.ordinal, o.section) for o in found}
        # 高声 W1 前句一次、W2 问答一次；低声 W3 问答一次
        self.assertIn(("高声", "W1", 1, "前句"), surfaces)
        self.assertIn(("高声", "W2", 1, "问答"), surfaces)
        self.assertIn(("低声", "W3", 1, "问答"), surfaces)

    def test_occurrence_filter_by_voice_and_section(self):
        high = self.corpus.find_occurrences("那厢", voice="高声")
        self.assertEqual({o.word_id for o in high}, {"W1", "W2"})
        qa = self.corpus.find_occurrences("那厢", voice="低声", section="问答")
        self.assertEqual(len(qa), 1)
        self.assertEqual(qa[0].context, "山那厢")
        self.assertEqual(qa[0].bars, (8, 9))

    def test_indices_point_back_to_source_text(self):
        occ = self.corpus.find_occurrences("那厢", voice="高声", section="问答")[0]
        lyric = self.corpus.lyric_at("高声", 8)
        for index in occ.indices:
            self.assertIn(lyric.text[index], "那厢")

    def test_latin_surface_match(self):
        found = self.corpus.find_occurrences("hold on", voice="高声")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].surface, "hold on")

    def test_same_voice_repeated_word_distinguished_by_context(self):
        # 高声两处“那厢”必须能区分是前句还是问答
        found = self.corpus.find_occurrences("那厢", voice="高声")
        contexts = {o.section: o.context for o in found}
        self.assertEqual(contexts["前句"], "山那厢")
        self.assertEqual(contexts["问答"], "莫唱山那厢")


if __name__ == "__main__":
    import unittest
    unittest.main()

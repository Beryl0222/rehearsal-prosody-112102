"""规划引擎：方案选择、确认纪律、阻断退回、备选与更正追溯。"""

from hechang.models import SegmentStatus
from tests._base import CorpusCase


class PlannerTest(CorpusCase):
    def test_plan_is_not_usable_when_shared_section_blocked(self):
        self.assertFalse(self.plan.usable)

    def test_solo_sections_confirmed_and_practice_ready(self):
        by_section = {v.section: v for v in self.plan.verdicts}
        self.assertEqual(by_section["前句"].status, SegmentStatus.CONFIRMED)
        self.assertEqual(by_section["尾句"].status, SegmentStatus.CONFIRMED)
        self.assertIn("前句", self.plan.practice_ready_sections)
        self.assertIn("尾句", self.plan.practice_ready_sections)

    def test_qa_section_blocked_and_returned_to_voices(self):
        qa = next(v for v in self.plan.verdicts if v.section == "问答")
        self.assertEqual(qa.status, SegmentStatus.BLOCKED)
        codes = {i.code for i in qa.issues}
        self.assertIn("SECTION_BLOCKED", codes)
        # 必须说清具体冲突在哪几句/哪几拍
        message = " ".join(i.message for i in qa.issues)
        self.assertIn("8:4", message)
        self.assertIn("9:2", message)

    def test_blocked_section_has_no_arrangement_but_alternatives_kept(self):
        qa_arrangements = [a for a in self.plan.arrangements if a.section == "问答"]
        self.assertEqual(qa_arrangements, [])
        alts = [a for a in self.plan.alternatives if a.section == "问答"]
        # 甲乙调与字面基线都应作为备选留下，并带否决原因
        reading_ids = {a.reading_id for a in alts}
        self.assertIn("NY1", reading_ids)
        self.assertIn("NY2", reading_ids)
        self.assertTrue(all(a.rejected_for for a in alts))

    def test_single_voice_approval_does_not_confirm_shared_section(self):
        # N3 只确认高声；即便联合合法，也不能替代低声确认
        approvals = [
            o for o in self.planner.opinions
            if o.action.value == "approve"
        ]
        voices = {o.voice for o in approvals}
        self.assertIn("高声", voices)
        # 高声的确认意见明确不覆盖低声（N3 原文“不替低声确认”）
        n3 = [o for o in approvals if o.note_id == "N3"]
        self.assertTrue(all(o.voice == "高声" for o in n3))

    def test_latest_correction_overrides_earlier_reading_choice(self):
        high_tries = [
            o for o in self.planner.opinions
            if o.voice == "高声" and o.section == "问答" and o.action.value == "try"
        ]
        self.assertEqual(high_tries[-1].note_id, "N5")
        self.assertEqual(high_tries[-1].region, "青岸乙调")

    def test_front_section_keeps_original_reading_after_n5(self):
        # N5“不动前句”：前句仍是 N1/N3 的甲调
        front = next(a for a in self.plan.arrangements
                     if a.section == "前句" and a.voice == "高声")
        self.assertEqual(front.reading_id, "NY1")

    def test_all_part_scores_share_one_selection_id(self):
        from hechang.render import render_manifest
        manifest = render_manifest(self.plan, self.corpus)
        # 方案内所有安排都挂同一 selection
        for arrangement in manifest["arrangements"]:
            self.assertIn(arrangement["reading_id"], {"NY1", "DEFAULT"})
        self.assertEqual(manifest["selection_id"], "SEL-2")

    def test_trace_quote_correction_locates_source_position(self):
        trace = self.planner.trace_correction(self.plan, "N5")
        self.assertEqual(trace["surface"], "莫唱")
        item = trace["items"][0]
        self.assertEqual(item["word_id"], "W2")
        self.assertEqual(item["indices"], [0, 1])
        self.assertEqual(item["section"], "问答")
        # 问答被阻断时不要求学员立刻重练
        self.assertEqual(item["status"], "blocked")

    def test_trace_unknown_note_raises(self):
        with self.assertRaises(KeyError):
            self.planner.trace_correction(self.plan, "NOPE")

    def test_manifest_locators_reference_source_word_ids(self):
        from hechang.render import render_manifest
        manifest = render_manifest(self.plan, self.corpus)
        word_ids = {
            placement["word_id"]
            for arrangement in manifest["arrangements"]
            for placement in arrangement["placements"]
        }
        self.assertTrue(word_ids <= {"W1", "W4"})


if __name__ == "__main__":
    import unittest
    unittest.main()

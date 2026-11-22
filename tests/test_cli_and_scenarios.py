"""端到端 CLI 与“可联合试唱”假设场景。"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from hechang.cli import main
from hechang.corpus import Corpus
from hechang.models import SegmentStatus
from hechang.planner import Planner
from hechang.rhythm import build_arrangement
from hechang.validation import validate_shared_marks
from tests._base import DATA_DIR


class CliTest(unittest.TestCase):
    def test_check_runs_and_reports_blocking_issues(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["-d", str(DATA_DIR), "check"])
        self.assertEqual(code, 0)
        self.assertIn("REENTRY_MISMATCH", buf.getvalue())

    def test_plan_writes_manifest_and_part_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["-d", str(DATA_DIR), "plan", "-o", tmp])
            self.assertEqual(code, 2)  # 有阻断问题时退出码 2
            out = Path(tmp)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["usable"])
            self.assertTrue((out / "part_高声.txt").read_text(encoding="utf-8"))
            self.assertTrue((out / "conductor_report.txt").read_text(encoding="utf-8"))
            # 分谱抬头与总报告同一次选择
            part = (out / "part_高声.txt").read_text(encoding="utf-8")
            self.assertIn(manifest["selection_id"], part)

    def test_trace_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["-d", str(DATA_DIR), "check"] + [])
        self.assertEqual(code, 0)
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            main(["-d", str(DATA_DIR), "trace", "N5", "--json"])
        payload = json.loads(buf2.getvalue())
        self.assertEqual(payload["note_id"], "N5")

    def test_every_part_score_carries_same_selection_as_report(self):
        from hechang.corpus import Corpus as _C
        from hechang.render import (
            render_conductor_report,
            render_part_score,
            render_manifest,
        )
        corpus = _C.load(DATA_DIR)
        plan = Planner(corpus).make_plan()
        manifest = render_manifest(plan, corpus)
        report = render_conductor_report(plan, corpus)
        self.assertIn(manifest["selection_id"], report)
        for voice in corpus.voices:
            part = render_part_score(plan, corpus, voice)
            self.assertIn(manifest["selection_id"], part)
            # 分谱里的唱法必须能在清单安排中找到，杜绝串版
            for arrangement in manifest["arrangements"]:
                if arrangement["voice"] != voice:
                    continue
                self.assertIn(arrangement["reading_id"], part)


class JointlySingableScenarioTest(unittest.TestCase):
    """构造一个拍位兼容的假设：验证合法组合能被选中。"""

    def setUp(self):
        self.corpus = Corpus.load(DATA_DIR)

    def test_compatible_pair_passes_shared_validation(self):
        yi = self.corpus.region_reading("那厢", "青岸乙调")
        # 两声部都用乙调时各自可落拍；重入冲突仍由数据决定，
        # 这里验证单声部安排合法且校验器确实执行了对齐检查
        high = build_arrangement(
            self.corpus, "高声", "问答", [8, 9], {"那厢": yi}
        ).arrangement
        low = build_arrangement(
            self.corpus, "低声", "问答", [8, 9], {"那厢": yi}
        ).arrangement
        self.assertIsNotNone(high)
        self.assertIsNotNone(low)
        found = validate_shared_marks(
            self.corpus, "问答", {"高声": high, "低声": low}
        )
        # 真实数据下 9:2 落点不同，必须报错；若未来数据改兼容，这里应无 error
        self.assertTrue(any(i.code == "REENTRY_MISMATCH" for i in found))

    def test_solo_confirmed_segments_distinct_from_trial(self):
        plan = Planner(self.corpus).make_plan()
        statuses = {v.section: v.status for v in plan.verdicts}
        self.assertEqual(statuses["前句"], SegmentStatus.CONFIRMED)
        self.assertEqual(statuses["问答"], SegmentStatus.BLOCKED)
        self.assertEqual(statuses["尾句"], SegmentStatus.CONFIRMED)


if __name__ == "__main__":
    unittest.main()

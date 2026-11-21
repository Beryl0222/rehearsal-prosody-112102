"""检查交换资料的标识、文本和跨表引用。"""

import json
from pathlib import Path
import unittest


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class SourceDataTest(unittest.TestCase):
    def setUp(self):
        self.tables = {}
        for path in sorted(DATA_DIR.glob("*.json")):
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(rows, list)
            self.assertTrue(rows, path.name)
            by_id = {}
            for row in rows:
                identifier = row["id"]
                self.assertIsInstance(identifier, str, path.name)
                self.assertNotIn(identifier, by_id, path.name)
                if "text" in row:
                    self.assertIsInstance(row["text"], str, path.name)
                by_id[identifier] = row
            self.tables[path.stem] = by_id

    def test_exchange_tables_present(self):
        self.assertEqual(set(self.tables), {'notes', 'score', 'words'})

    def test_related_source_records(self):
        data = self.tables
        score = data["score"]
        staff = {(row["bar"], row["voice"]) for row in score.values()}
        for row in data["words"].values():
            for bar in row.get("bars", []):
                self.assertIn((bar, row["voice"]), staff)
        for row in score.values():
            available = {slot["beat"] for slot in row["slots"]}
            self.assertTrue(all(set(beats) <= available for beats in row["shared"].values()))
        self.assertEqual(data["words"]["NY1"]["surface"], data["words"]["NY2"]["surface"])
        self.assertNotEqual(data["words"]["NY1"]["syllables"], data["words"]["NY2"]["syllables"])

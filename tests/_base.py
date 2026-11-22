"""共享测试夹具。"""

import unittest
from pathlib import Path

from hechang.corpus import Corpus
from hechang.planner import Planner

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class CorpusCase(unittest.TestCase):
    def setUp(self):
        self.corpus = Corpus.load(DATA_DIR)
        self.planner = Planner(self.corpus)
        self.plan = self.planner.make_plan()

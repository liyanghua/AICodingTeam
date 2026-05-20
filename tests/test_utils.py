from __future__ import annotations

import unittest

from growth_dev.utils import parse_count, slugify


class UtilsTests(unittest.TestCase):
    def test_parse_count_handles_chinese_units(self) -> None:
        self.assertEqual(parse_count("1.2万"), 12000)
        self.assertEqual(parse_count("999+"), 999)
        self.assertEqual(parse_count("3k"), 3000)
        self.assertEqual(parse_count("2亿"), 200000000)

    def test_slugify(self) -> None:
        self.assertEqual(slugify("  露营 / 笔记  "), "露营-笔记")


if __name__ == "__main__":
    unittest.main()

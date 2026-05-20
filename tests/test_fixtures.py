from __future__ import annotations

import unittest

from growth_dev.fixtures import build_candidate_cards, sort_cards_by_comments


class FixtureTests(unittest.TestCase):
    def test_candidate_cards_are_deterministic(self) -> None:
        first = build_candidate_cards("露营", candidate_pool=12)
        second = build_candidate_cards("露营", candidate_pool=12)
        self.assertEqual([card.note.note_id for card in first], [card.note.note_id for card in second])

    def test_sort_by_comments_descending(self) -> None:
        cards = build_candidate_cards("咖啡", candidate_pool=20)
        sorted_cards = sort_cards_by_comments(cards)
        counts = [card.note.counts.comments for card in sorted_cards]
        self.assertEqual(counts, sorted(counts, reverse=True))


if __name__ == "__main__":
    unittest.main()

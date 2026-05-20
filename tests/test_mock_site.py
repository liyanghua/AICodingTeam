from __future__ import annotations

import unittest

from growth_dev.fixtures import build_candidate_cards
from growth_dev.mock_site import render_note_page, render_search_page


class MockSiteTests(unittest.TestCase):
    def test_render_search_page_contains_cards(self) -> None:
        cards = build_candidate_cards("露营", candidate_pool=8)
        html = render_search_page("露营", page=1, cards=cards, page_size=5)
        self.assertIn("Search results for 露营", html)
        self.assertIn('data-testid="note-card"', html)

    def test_render_note_page_contains_comments(self) -> None:
        note = build_candidate_cards("咖啡", candidate_pool=5)[0].note
        html = render_note_page(note)
        self.assertIn(note.title, html)
        self.assertIn('data-testid="comment"', html)


if __name__ == "__main__":
    unittest.main()

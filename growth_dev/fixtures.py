from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Iterable

from .models import AuthorInfo, Comment, CommentReply, Counts, MediaItem, XhsNote
from .utils import stable_seed


@dataclass(slots=True)
class SearchCard:
    rank: int
    note: XhsNote
    excerpt: str
    relevance: float


AUTHORS = [
    ("山野笔记", "https://www.xiaohongshu.com/user/profile/alpha"),
    ("咖啡豆观察员", "https://www.xiaohongshu.com/user/profile/bravo"),
    ("内容方法论", "https://www.xiaohongshu.com/user/profile/charlie"),
    ("周末出走指南", "https://www.xiaohongshu.com/user/profile/delta"),
    ("效率实验室", "https://www.xiaohongshu.com/user/profile/echo"),
]

MEDIA_TYPES = ["image", "video"]


def _rng(keyword: str, index: int) -> Random:
    return Random(stable_seed(keyword, str(index)))


def _sentence(keyword: str, index: int, part: int) -> str:
    templates = [
        f"{keyword} 第{index}篇的现场记录很完整，适合直接做行动清单。",
        f"这篇笔记强调的是实操细节，而不是泛泛而谈。",
        f"里面把步骤、物料和避坑点都写得比较清楚。",
        f"如果你要做一个同类选题，这篇的结构很适合参考。",
    ]
    return templates[(index + part) % len(templates)]


def build_note(keyword: str, rank: int, base_url: str = "http://127.0.0.1:8787") -> XhsNote:
    rng = _rng(keyword, rank)
    author_name, author_url = AUTHORS[(rank + rng.randint(0, len(AUTHORS) - 1)) % len(AUTHORS)]
    count_base = 520 - rank * 11 + rng.randint(-35, 75)
    comments = max(18, count_base)
    likes = comments * (2 + rng.randint(0, 3))
    collects = max(8, comments // 2 + rng.randint(-8, 22))
    shares = max(2, comments // 12 + rng.randint(0, 5))

    note_id = f"{keyword}-{rank:03d}"
    url = f"{base_url}/note?keyword={keyword}&rank={rank}"
    title = f"{keyword} 真实采集样例 #{rank}"
    body = " ".join(_sentence(keyword, rank, part) for part in range(4))

    media: list[MediaItem] = []
    image_count = 2 + rng.randint(0, 2)
    for i in range(image_count):
        media.append(
            MediaItem(
                type="image",
                visible_url=f"{base_url}/static/{note_id}-image-{i + 1}.jpg",
                screenshot_path="",
                alt_text=f"{keyword} 图片 {i + 1}",
            )
        )
    if rank % 4 == 0:
        media.append(
            MediaItem(
                type="video",
                visible_url=f"{base_url}/static/{note_id}-video.mp4",
                screenshot_path="",
                alt_text=f"{keyword} 视频片段",
            )
        )

    total_comments = min(comments, 60)
    comment_items: list[Comment] = []
    for comment_index in range(total_comments):
        reply_count = 0
        if comment_index < 8 and comment_index % 2 == 0:
            reply_count = 1 + rng.randint(0, 2)
        replies = [
            CommentReply(
                text=f"二级评论 {comment_index + 1}-{reply_index + 1}，补充了操作细节。",
                like_count=rng.randint(0, 12),
            )
            for reply_index in range(reply_count)
        ]
        comment_items.append(
            Comment(
                text=f"一级评论 {comment_index + 1}：这个内容对 {keyword} 很有帮助。",
                like_count=rng.randint(0, 88),
                replies=replies,
            )
        )

    note = XhsNote(
        note_id=note_id,
        url=url,
        title=title,
        body=body,
        author=AuthorInfo(display_name=author_name, profile_url=author_url),
        counts=Counts(likes=likes, collects=collects, comments=comments, shares=shares),
        media=media,
        comments=comment_items,
        extraction_meta={},
    )
    return note


def build_candidate_cards(keyword: str, candidate_pool: int = 100, base_url: str = "http://127.0.0.1:8787") -> list[SearchCard]:
    cards: list[SearchCard] = []
    rng = Random(stable_seed(keyword, "search"))
    for rank in range(1, candidate_pool + 1):
        note = build_note(keyword, rank, base_url=base_url)
        relevance = rng.random()
        excerpt = note.body[:92] + ("…" if len(note.body) > 92 else "")
        cards.append(SearchCard(rank=rank, note=note, excerpt=excerpt, relevance=relevance))
    rng.shuffle(cards)
    return cards


def sort_cards_by_comments(cards: Iterable[SearchCard]) -> list[SearchCard]:
    return sorted(cards, key=lambda card: (card.note.counts.comments, card.relevance), reverse=True)


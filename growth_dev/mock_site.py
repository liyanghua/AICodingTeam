from __future__ import annotations

from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

from .fixtures import SearchCard, build_candidate_cards, sort_cards_by_comments
from .models import XhsNote
from .utils import ensure_dir


def _render_page(title: str, body: str, search_value: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #6b7280;
      --line: #d7dde8;
      --accent: #2563eb;
      --accent-soft: rgba(37, 99, 235, 0.08);
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header, main {{
      max-width: 1160px;
      margin: 0 auto;
      padding: 24px;
    }}
    .shell {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 20px;
    }}
    .searchbar {{
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 16px;
    }}
    input, button, a.btn {{
      font: inherit;
      border-radius: 8px;
      border: 1px solid var(--line);
      padding: 10px 12px;
    }}
    button, a.btn {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 16px;
      margin-bottom: 12px;
      background: white;
    }}
    .grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }}
    .media img, .media video {{
      width: 100%;
      display: block;
      border-radius: 10px;
      background: #e5e7eb;
    }}
    .muted {{ color: var(--muted); }}
    .comment {{
      border-left: 3px solid var(--accent-soft);
      padding-left: 12px;
      margin-top: 12px;
    }}
    .reply {{
      margin-left: 18px;
      margin-top: 8px;
      color: #394150;
    }}
    .state {{ background: #fff7ed; color: #9a3412; padding: 10px 12px; border-radius: 8px; }}
  </style>
</head>
<body>
  <header>
    <div class="shell">
      <form class="searchbar" action="/search" method="get">
        <input name="keyword" value="{escape(search_value)}" placeholder="输入关键词" aria-label="关键词" />
        <button type="submit">搜索</button>
      </form>
      <div class="muted">Mock XHS benchmark surface for local automation testing.</div>
    </div>
  </header>
  <main>
    {body}
  </main>
</body>
</html>"""


def render_home() -> str:
    body = """
    <section class="card">
      <h1>XHS Mock Benchmark</h1>
      <p class="muted">Use the search bar to inspect deterministic candidate notes.</p>
      <div class="state">Manual login is not required on the mock site.</div>
    </section>
    """
    return _render_page("XHS Mock - Home", body, search_value="")


def render_search_page(keyword: str, page: int, cards: list[SearchCard], page_size: int = 12) -> str:
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    subset = cards[start:end]
    cards_html = []
    for card in subset:
        note = card.note
        cards_html.append(
            f"""
            <article class="card" data-testid="note-card" data-note-id="{escape(note.note_id)}">
              <h2><a href="{escape(note.url)}">{escape(note.title)}</a></h2>
              <div class="muted">作者：{escape(note.author.display_name)} · 评论数：<strong>{note.counts.comments}</strong></div>
              <p>{escape(card.excerpt)}</p>
              <div class="grid">
                {''.join(_render_media_preview(item) for item in note.media[:4])}
              </div>
            </article>
            """
        )
    if not subset:
        cards_html.append('<div class="card state">No results for this keyword.</div>')

    pagination = []
    if start > 0:
        pagination.append(f'<a class="btn" href="/search?keyword={escape(keyword)}&page={page - 1}">上一页</a>')
    if end < len(cards):
        pagination.append(f'<a class="btn" href="/search?keyword={escape(keyword)}&page={page + 1}">下一页</a>')

    body = f"""
    <section class="card">
      <h1>Search results for {escape(keyword)}</h1>
      <p class="muted">Cards are intentionally not sorted by comment count. The harness must sort locally.</p>
      <div class="muted">Total candidates: {len(cards)}</div>
    </section>
    {''.join(cards_html)}
    <section class="card">
      {' '.join(pagination) if pagination else '<span class="muted">No more pages.</span>'}
    </section>
    """
    return _render_page(f"XHS Mock - {keyword}", body, search_value=keyword)


def _render_media_preview(item: Any) -> str:
    if item.type == "video":
        return f'<video controls muted poster="{escape(item.visible_url)}" aria-label="{escape(item.alt_text)}"></video>'
    return f'<img src="{escape(item.visible_url)}" alt="{escape(item.alt_text)}" />'


def _render_comment_block(note: XhsNote, offset: int, limit: int) -> str:
    visible = note.comments[offset : offset + limit]
    blocks = []
    for index, comment in enumerate(visible, start=offset + 1):
        replies = "".join(
            f'<div class="reply" data-testid="reply"><strong>回复：</strong>{escape(reply.text)} · 赞 {reply.like_count}</div>'
            for reply in comment.replies
        )
        blocks.append(
            f"""
            <div class="comment" data-testid="comment" data-comment-index="{index}">
              <div><strong>评论 {index}</strong> · 赞 {comment.like_count}</div>
              <div>{escape(comment.text)}</div>
              {replies}
            </div>
            """
        )
    if not blocks:
        blocks.append('<div class="state">暂无更多评论。</div>')
    return "".join(blocks)


def render_note_page(note: XhsNote, comments_offset: int = 0, comments_limit: int = 8) -> str:
    next_offset = comments_offset + comments_limit
    load_more = ""
    if next_offset < len(note.comments):
        load_more = (
            f'<a class="btn" href="{escape(note.url)}&comments_offset={next_offset}&comments_limit={comments_limit}">'
            "加载更多评论"
            "</a>"
        )

    media_html = "".join(
        f'<div class="card media" data-testid="media">{_render_media_preview(item)}</div>' for item in note.media
    )
    comments_html = _render_comment_block(note, comments_offset, comments_limit)

    body = f"""
    <article class="card" data-testid="note-detail" data-note-id="{escape(note.note_id)}">
      <h1>{escape(note.title)}</h1>
      <div class="muted">作者：{escape(note.author.display_name)} · 评论数：{note.counts.comments} · 赞：{note.counts.likes} · 收藏：{note.counts.collects}</div>
      <p>{escape(note.body)}</p>
    </article>
    <section class="grid">{media_html}</section>
    <section class="card">
      <h2>评论</h2>
      <div class="muted">已展示 {min(comments_offset + comments_limit, len(note.comments))} / {len(note.comments)}</div>
      {comments_html}
      <div style="margin-top: 16px;">{load_more}</div>
    </section>
    """
    return _render_page(f"XHS Mock - {note.title}", body, search_value=note.title)


class MockXhsDataSource:
    def __init__(self, keyword: str, candidate_pool: int = 100, base_url: str = "http://127.0.0.1:8787") -> None:
        self.keyword = keyword
        self.candidate_pool = candidate_pool
        self.base_url = base_url
        self.cards = build_candidate_cards(keyword, candidate_pool=candidate_pool, base_url=base_url)

    def sorted_cards(self) -> list[SearchCard]:
        return sort_cards_by_comments(self.cards)

    def note_for_rank(self, rank: int) -> XhsNote:
        sorted_cards = self.sorted_cards()
        for card in sorted_cards:
            if card.rank == rank:
                return card.note
        return sorted_cards[0].note


class MockXhsRequestHandler(BaseHTTPRequestHandler):
    data_root = MockXhsDataSource("露营")

    def _send_html(self, text: str, status: int = 200) -> None:
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        import json

        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            return self._send_html(render_home())
        if parsed.path == "/api/search":
            keyword = query.get("keyword", ["露营"])[0]
            candidate_pool = int(query.get("candidate_pool", ["100"])[0])
            data = MockXhsDataSource(keyword=keyword, candidate_pool=candidate_pool, base_url=self.server.base_url)  # type: ignore[attr-defined]
            return self._send_json(
                {
                    "keyword": keyword,
                    "cards": [
                        {
                            "rank": card.rank,
                            "note": card.note.to_dict(),
                            "excerpt": card.excerpt,
                        }
                        for card in data.cards
                    ],
                }
            )
        if parsed.path == "/search":
            keyword = query.get("keyword", ["露营"])[0]
            page = int(query.get("page", ["1"])[0])
            candidate_pool = int(query.get("candidate_pool", ["100"])[0])
            data = MockXhsDataSource(keyword=keyword, candidate_pool=candidate_pool, base_url=self.server.base_url)  # type: ignore[attr-defined]
            return self._send_html(render_search_page(keyword, page, data.cards))
        if parsed.path == "/note":
            keyword = query.get("keyword", ["露营"])[0]
            rank = int(query.get("rank", ["1"])[0])
            comments_offset = int(query.get("comments_offset", ["0"])[0])
            comments_limit = int(query.get("comments_limit", ["8"])[0])
            data = MockXhsDataSource(keyword=keyword, candidate_pool=100, base_url=self.server.base_url)  # type: ignore[attr-defined]
            return self._send_html(
                render_note_page(
                    data.note_for_rank(rank),
                    comments_offset=comments_offset,
                    comments_limit=comments_limit,
                )
            )
        return self._send_html(_render_page("Not Found", '<div class="card state">404</div>'), status=404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


@dataclass(slots=True)
class MockServer:
    host: str = "127.0.0.1"
    port: int = 8787
    base_dir: Path = Path("runs/mock-site")

    server: ThreadingHTTPServer | None = None
    thread: Thread | None = None

    def start(self) -> str:
        ensure_dir(self.base_dir)
        handler = MockXhsRequestHandler
        self.server = ThreadingHTTPServer((self.host, self.port), handler)
        actual_port = self.server.server_address[1]
        self.server.base_url = f"http://{self.host}:{actual_port}"  # type: ignore[attr-defined]
        thread = Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.thread = thread
        return self.server.base_url  # type: ignore[return-value]

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.thread = None

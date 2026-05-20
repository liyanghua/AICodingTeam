from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Self


@dataclass(slots=True)
class AuthorInfo:
    display_name: str
    profile_url: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            display_name=str(data.get("display_name", "")),
            profile_url=str(data.get("profile_url", "")),
        )


@dataclass(slots=True)
class Counts:
    likes: int = 0
    collects: int = 0
    comments: int = 0
    shares: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            likes=int(data.get("likes", 0) or 0),
            collects=int(data.get("collects", 0) or 0),
            comments=int(data.get("comments", 0) or 0),
            shares=int(data.get("shares", 0) or 0),
        )


@dataclass(slots=True)
class MediaItem:
    type: str
    visible_url: str
    screenshot_path: str = ""
    alt_text: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            type=str(data.get("type", "image")),
            visible_url=str(data.get("visible_url", "")),
            screenshot_path=str(data.get("screenshot_path", "")),
            alt_text=str(data.get("alt_text", "")),
        )


@dataclass(slots=True)
class CommentReply:
    text: str
    like_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            text=str(data.get("text", "")),
            like_count=int(data.get("like_count", 0) or 0),
        )


@dataclass(slots=True)
class Comment:
    text: str
    like_count: int = 0
    replies: list[CommentReply] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            text=str(data.get("text", "")),
            like_count=int(data.get("like_count", 0) or 0),
            replies=[CommentReply.from_dict(item) for item in data.get("replies", [])],
        )


@dataclass(slots=True)
class XhsNote:
    note_id: str
    url: str
    title: str
    body: str
    author: AuthorInfo
    counts: Counts
    media: list[MediaItem] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    extraction_meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            note_id=str(data.get("note_id", "")),
            url=str(data.get("url", "")),
            title=str(data.get("title", "")),
            body=str(data.get("body", "")),
            author=AuthorInfo.from_dict(data.get("author", {})),
            counts=Counts.from_dict(data.get("counts", {})),
            media=[MediaItem.from_dict(item) for item in data.get("media", [])],
            comments=[Comment.from_dict(item) for item in data.get("comments", [])],
            extraction_meta=dict(data.get("extraction_meta", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def total_reply_count(self) -> int:
        return sum(len(comment.replies) for comment in self.comments)


@dataclass(slots=True)
class TaskSpec:
    task_id: str
    title: str
    keyword: str
    top_n: int = 20
    candidate_pool: int = 100
    max_comments_per_note: int = 500
    mode: str = "headed_low_frequency"
    profile_dir: Path = Path(".local/browser-profiles/xhs")
    frameworks: list[str] = field(default_factory=list)
    base_url: str = "http://127.0.0.1:8787"
    suite: str = "pilot"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            task_id=str(data.get("task_id", "xhs-framework-benchmark")),
            title=str(data.get("title", "XHS browser framework benchmark")),
            keyword=str(data.get("keyword", "露营")),
            top_n=int(data.get("top_n", 20) or 20),
            candidate_pool=int(data.get("candidate_pool", 100) or 100),
            max_comments_per_note=int(data.get("max_comments_per_note", 500) or 500),
            mode=str(data.get("mode", "headed_low_frequency")),
            profile_dir=Path(data.get("profile_dir", ".local/browser-profiles/xhs")),
            frameworks=list(data.get("frameworks", [])),
            base_url=str(data.get("base_url", "http://127.0.0.1:8787")),
            suite=str(data.get("suite", "pilot")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile_dir"] = str(self.profile_dir)
        return payload


@dataclass(slots=True)
class RunMetrics:
    elapsed_ms: int = 0
    retry_count: int = 0
    crash_count: int = 0
    manual_interventions: int = 0
    token_cost: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            elapsed_ms=int(data.get("elapsed_ms", 0) or 0),
            retry_count=int(data.get("retry_count", 0) or 0),
            crash_count=int(data.get("crash_count", 0) or 0),
            manual_interventions=int(data.get("manual_interventions", 0) or 0),
            token_cost=float(data.get("token_cost", 0.0) or 0.0),
        )


@dataclass(slots=True)
class AdapterResult:
    framework: str
    status: str
    notes: list[XhsNote] = field(default_factory=list)
    risk_events: list[str] = field(default_factory=list)
    metrics: RunMetrics = field(default_factory=RunMetrics)
    stdout_path: str = ""
    stderr_path: str = ""
    exit_code: int = 0
    runner: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            framework=str(data.get("framework", "")),
            status=str(data.get("status", "unknown")),
            notes=[XhsNote.from_dict(item) for item in data.get("notes", [])],
            risk_events=[str(item) for item in data.get("risk_events", [])],
            metrics=RunMetrics.from_dict(data.get("metrics", {})),
            stdout_path=str(data.get("stdout_path", "")),
            stderr_path=str(data.get("stderr_path", "")),
            exit_code=int(data.get("exit_code", 0) or 0),
            runner=str(data.get("runner", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["notes"] = [note.to_dict() for note in self.notes]
        return payload


@dataclass(slots=True)
class RunRecord:
    run_id: str
    task: TaskSpec
    adapter_results: list[AdapterResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    base_dir: Path = Path("runs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task.to_dict(),
            "adapter_results": [result.to_dict() for result in self.adapter_results],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "base_dir": str(self.base_dir),
        }

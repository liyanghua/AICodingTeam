from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TemplateMatch:
    name: str
    score: float
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


class TemplateMatcher:
    def __init__(self, match_threshold: float = 0.86) -> None:
        self.match_threshold = match_threshold

    def filter_matches(self, matches: list[TemplateMatch]) -> list[TemplateMatch]:
        return sorted(
            [match for match in matches if match.score >= self.match_threshold],
            key=lambda match: match.score,
            reverse=True,
        )

    def match_files(self, screenshot_path: Path, template_dir: Path) -> list[TemplateMatch]:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "opencv-python is required for template fallback matching"
            ) from exc
        if not template_dir.exists():
            return []
        screenshot = cv2.imread(str(screenshot_path))
        if screenshot is None:
            return []
        matches: list[TemplateMatch] = []
        for template_path in sorted(template_dir.glob("*.png")):
            template = cv2.imread(str(template_path))
            if template is None:
                continue
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            _, max_value, _, max_location = cv2.minMaxLoc(result)
            height, width = template.shape[:2]
            matches.append(
                TemplateMatch(
                    name=template_path.stem,
                    score=float(max_value),
                    x=int(max_location[0]),
                    y=int(max_location[1]),
                    width=int(width),
                    height=int(height),
                )
            )
        return self.filter_matches(matches)

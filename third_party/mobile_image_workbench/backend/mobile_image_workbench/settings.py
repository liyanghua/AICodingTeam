from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_JOB_MODES = {"single_image", "batch_images", "config_file"}
DEFAULT_TARGET_CATEGORY = "桌垫"
DEFAULT_TARGET_CATEGORY_KEYWORDS = ["桌垫", "餐桌垫", "餐垫", "桌垫桌布"]


@dataclass(frozen=True)
class JobSettings:
    mode: str
    image_top_n: int
    keyword_top_n: int
    keyword_result_top_n: int
    device_serial: str | None = None
    deterministic_mode: bool = True
    max_result_scrolls: int = 10
    throttle_seconds: float = 3.0
    subject_recognition_wait_seconds: float = 5.0
    category_filter_enabled: bool = False
    target_category: str = DEFAULT_TARGET_CATEGORY
    target_category_keywords: list[str] = field(
        default_factory=lambda: list(DEFAULT_TARGET_CATEGORY_KEYWORDS)
    )
    dry_run: bool = False

    @classmethod
    def for_mode(cls, mode: str) -> "JobSettings":
        if mode not in SUPPORTED_JOB_MODES:
            raise ValueError(f"unsupported job mode: {mode}")
        if mode == "config_file":
            return cls(
                mode=mode,
                image_top_n=10,
                keyword_top_n=4,
                keyword_result_top_n=5,
            )
        return cls(
            mode=mode,
            image_top_n=10,
            keyword_top_n=0,
            keyword_result_top_n=0,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "JobSettings":
        settings_payload = payload.get("settings") or {}
        mode = str(settings_payload.get("mode") or payload.get("mode") or "").strip()
        if not mode:
            mode = "config_file" if payload.get("configFile") else "single_image"
        defaults = cls.for_mode(mode)
        settings = cls(
            mode=mode,
            image_top_n=_int_value(
                settings_payload, "imageTopN", "image_top_n", defaults.image_top_n
            ),
            keyword_top_n=_int_value(
                settings_payload, "keywordTopN", "keyword_top_n", defaults.keyword_top_n
            ),
            keyword_result_top_n=_int_value(
                settings_payload,
                "keywordResultTopN",
                "keyword_result_top_n",
                defaults.keyword_result_top_n,
            ),
            device_serial=_optional_str(
                settings_payload.get("deviceSerial")
                if "deviceSerial" in settings_payload
                else settings_payload.get("device_serial")
            ),
            deterministic_mode=_bool_value(
                settings_payload,
                "deterministicMode",
                "deterministic_mode",
                defaults.deterministic_mode,
            ),
            max_result_scrolls=_int_value(
                settings_payload,
                "maxResultScrolls",
                "max_result_scrolls",
                defaults.max_result_scrolls,
            ),
            throttle_seconds=float(
                _first_present(
                    settings_payload,
                    ("throttleSeconds", "throttle_seconds"),
                    defaults.throttle_seconds,
                )
            ),
            subject_recognition_wait_seconds=float(
                _first_present(
                    settings_payload,
                    (
                        "subjectRecognitionWaitSeconds",
                        "subject_recognition_wait_seconds",
                    ),
                    defaults.subject_recognition_wait_seconds,
                )
            ),
            category_filter_enabled=_bool_value(
                settings_payload,
                "categoryFilterEnabled",
                "category_filter_enabled",
                defaults.category_filter_enabled,
            ),
            target_category=str(
                _first_present(
                    settings_payload,
                    ("targetCategory", "target_category"),
                    defaults.target_category,
                )
            ).strip(),
            target_category_keywords=_string_list(
                _first_present(
                    settings_payload,
                    ("targetCategoryKeywords", "target_category_keywords"),
                    defaults.resolved_target_category_keywords,
                )
            ),
            dry_run=_bool_value(
                settings_payload, "dryRun", "dry_run", defaults.dry_run
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in SUPPORTED_JOB_MODES:
            raise ValueError(f"unsupported job mode: {self.mode}")
        if self.image_top_n < 1:
            raise ValueError("image_top_n must be >= 1")
        if self.keyword_top_n < 0:
            raise ValueError("keyword_top_n must be >= 0")
        if self.keyword_result_top_n < 0:
            raise ValueError("keyword_result_top_n must be >= 0")
        if self.max_result_scrolls < 1:
            raise ValueError("max_result_scrolls must be >= 1")
        if self.throttle_seconds < 0:
            raise ValueError("throttle_seconds must be >= 0")
        if self.subject_recognition_wait_seconds < 0:
            raise ValueError("subject_recognition_wait_seconds must be >= 0")

    @property
    def resolved_target_category_keywords(self) -> list[str]:
        return _string_list(self.target_category_keywords)

    @property
    def effective_target_category_keywords(self) -> list[str]:
        if not self.category_filter_enabled:
            return []
        return self.resolved_target_category_keywords

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "imageTopN": self.image_top_n,
            "keywordTopN": self.keyword_top_n,
            "keywordResultTopN": self.keyword_result_top_n,
            "deviceSerial": self.device_serial,
            "deterministicMode": self.deterministic_mode,
            "maxResultScrolls": self.max_result_scrolls,
            "throttleSeconds": self.throttle_seconds,
            "subjectRecognitionWaitSeconds": self.subject_recognition_wait_seconds,
            "categoryFilterEnabled": self.category_filter_enabled,
            "targetCategory": self.target_category,
            "targetCategoryKeywords": self.resolved_target_category_keywords,
            "dryRun": self.dry_run,
        }


def _first_present(
    payload: dict[str, Any], keys: tuple[str, str], default: Any
) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _int_value(
    payload: dict[str, Any], camel_key: str, snake_key: str, default: int
) -> int:
    return int(_first_present(payload, (camel_key, snake_key), default))


def _bool_value(
    payload: dict[str, Any], camel_key: str, snake_key: str, default: bool
) -> bool:
    value = _first_present(payload, (camel_key, snake_key), default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_parts = _split_keyword_text(value)
    elif isinstance(value, (list, tuple)):
        raw_parts = []
        for item in value:
            raw_parts.extend(_split_keyword_text(str(item)))
    else:
        raw_parts = _split_keyword_text(str(value))
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        text = " ".join(raw.split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _split_keyword_text(value: str) -> list[str]:
    import re

    return re.split(r"[,，\n\r]+", value)

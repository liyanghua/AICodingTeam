from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, read_json, write_json
from .reference_index import (
    INDEX_JSON_NAME as REFERENCE_INDEX_JSON_NAME,
    INDEX_MD_NAME as REFERENCE_INDEX_MD_NAME,
    build_reference_app_index,
    write_reference_app_index_artifacts,
)
from .yaml_io import load_yaml_subset


APP_GENERATION_DOMAIN_ID = "app_generation"
APP_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SECRET_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)((api[_-]?key|secret|token|password|dsn)\s*[:=]\s*)[^\s,;'\"\n]+"),
)

BENCHMARK_CAPABILITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "product_image_upload": ("type=\"file\"", "productimage", "产品图"),
    "reference_image_upload": ("type=\"file\"", "referenceimage", "参考图"),
    "image_provider_proxy": ("/api/images/generate", "openai", "openrouter"),
    "single_image_generation": ("generateimage(", "generate-single", "单张", "data-action=\"generate\""),
    "batch_image_generation": ("batchgenerate(", "batch-generate", "generateall", "生成全部", "批量"),
    "prompt_download": ("downloadprompt", "下载 prompt", "download-prompt"),
    "image_download": ("downloadimage", "下载图片", "download-image"),
    "provider_setup_error": ("provider_not_configured", "not configured", "未配置", "setup error"),
}

PLACEHOLDER_SECRET_MARKERS = (
    "sk-your",
    "sk-or-your",
    "your-",
    "placeholder",
    "changeme",
    "example",
    "<redacted",
)


def is_app_generation_domain(domain: Any) -> bool:
    return getattr(domain, "domain_id", "") == APP_GENERATION_DOMAIN_ID


def validate_app_slug(value: Any) -> str:
    slug = str(value or "").strip()
    if not APP_SLUG_PATTERN.fullmatch(slug):
        raise ValueError("app_slug must use lowercase letters, numbers, and hyphens only")
    if any(marker in slug for marker in (".", "/", "\\", "..")):
        raise ValueError("app_slug must not contain path traversal characters")
    return slug


def prepare_app_generation_artifacts(*, run_id: str, run_dir: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(run_dir)
    app_slug = validate_app_slug(inputs.get("app_slug"))
    prd_text, source = _load_prd_input(inputs)
    redacted_prd = redact_text(prd_text)
    generated_app_dir = f"generated_apps/{app_slug}"
    preview_port = int(inputs.get("preview_port") or 8788)
    preview_url = f"http://127.0.0.1:{preview_port}"
    allowed_paths = [
        f"{generated_app_dir}/",
        "tests/",
        "domains/app_generation/",
        "docs/",
    ]
    verification_commands = [
        f"node --check {generated_app_dir}/server.js",
        f"node {generated_app_dir}/runtime_smoke.js",
        "python3 -m unittest discover -s tests -v",
    ]
    benchmark_context = _load_benchmark_context(source)
    quality_mode = "benchmark_parity" if benchmark_context else "prototype"

    ensure_dir(run_dir / "requirements")
    (run_dir / "input_prd.md").write_text(_input_prd_markdown(prd_text, source), encoding="utf-8")
    (run_dir / "requirements" / "normalized_prd.md").write_text(
        _normalized_prd_markdown(redacted_prd, app_slug, generated_app_dir),
        encoding="utf-8",
    )
    contract = _app_contract(
        app_slug=app_slug,
        generated_app_dir=generated_app_dir,
        preview_url=preview_url,
        verification_commands=verification_commands,
        quality_mode=quality_mode,
        benchmark_context=benchmark_context,
    )
    write_json(run_dir / "app_contract.json", contract)
    (run_dir / "preview_instructions.md").write_text(_preview_instructions(contract), encoding="utf-8")
    output_paths = [
        "input_prd.md",
        "requirements/normalized_prd.md",
        "app_contract.json",
        "preview_instructions.md",
    ]
    if benchmark_context:
        write_json(run_dir / "benchmark_context.json", benchmark_context)
        (run_dir / "benchmark_context.md").write_text(_benchmark_context_markdown(benchmark_context), encoding="utf-8")
        output_paths.extend(["benchmark_context.json", "benchmark_context.md"])
        reference_dir = Path(benchmark_context.get("reference_app_dir", ""))
        if reference_dir.exists() and reference_dir.is_dir():
            index_payload = build_reference_app_index(
                reference_dir,
                benchmark_context.get("required_capabilities", []),
            )
            write_reference_app_index_artifacts(run_dir, index_payload)
            output_paths.extend([REFERENCE_INDEX_JSON_NAME, REFERENCE_INDEX_MD_NAME])

    return {
        "run_id": run_id,
        "app_slug": app_slug,
        "quality_mode": quality_mode,
        "prd_text": prd_text,
        "redacted_prd_text": redacted_prd,
        "summary": _compact(redacted_prd, 240),
        "source": source,
        "generated_app_dir": generated_app_dir,
        "allowed_paths": allowed_paths,
        "verification_commands": verification_commands,
        "app_contract": contract,
        "benchmark_context": benchmark_context,
        "output_paths": output_paths,
    }


def app_generation_acceptance_criteria(context: dict[str, Any]) -> list[dict[str, Any]]:
    app_slug = str(context["app_slug"])
    generated_app_dir = str(context["generated_app_dir"])
    return [
        {
            "id": "AC-001",
            "description": "The original PRD is persisted as `input_prd.md` and remains auditable.",
            "observable": True,
            "testable": True,
            "source": "app_generation_contract",
        },
        {
            "id": "AC-002",
            "description": "`requirements/normalized_prd.md` names the app goal, workflow, scope boundaries, assumptions, and blockers.",
            "observable": True,
            "testable": True,
            "source": "app_generation_contract",
        },
        {
            "id": "AC-003",
            "description": "`app_contract.json` fixes v1 stack as native SPA, Node stdlib server, localStorage, and no database.",
            "observable": True,
            "testable": True,
            "source": "app_generation_contract",
        },
        {
            "id": "AC-004",
            "description": f"Generated app code is scoped to `{generated_app_dir}/` and supporting allowed paths only.",
            "observable": True,
            "testable": True,
            "source": "app_generation_contract",
        },
        {
            "id": "AC-005",
            "description": f"The app `{app_slug}` includes local preview instructions and a Node server syntax check.",
            "observable": True,
            "testable": True,
            "source": "app_generation_contract",
        },
        {
            "id": "AC-006",
            "description": "Browser persistence uses localStorage only; no database, migration, or secret storage is generated.",
            "observable": True,
            "testable": True,
            "source": "app_generation_contract",
        },
        {
            "id": "AC-007",
            "description": "Unsupported PRD requests are recorded as blockers, assumptions, or mocked behavior instead of being hidden.",
            "observable": True,
            "testable": True,
            "source": "app_generation_contract",
        },
    ]


def redact_text(value: str) -> str:
    redacted = str(value)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: (match.group(1) + "<redacted>") if match.lastindex else "<redacted-secret>", redacted)
    return redacted


def _load_prd_input(inputs: dict[str, Any]) -> tuple[str, str]:
    prd_file = str(inputs.get("prd_file") or "").strip()
    prd_text = str(inputs.get("prd_text") or "").strip()
    parts: list[str] = []
    source = "prd_text"
    if prd_file:
        path = _safe_prd_file(prd_file)
        parts.append(path.read_text(encoding="utf-8"))
        source = f"prd_file:{prd_file}"
    if prd_text:
        if parts:
            parts.extend(["", "## Supplemental PRD Text", "", prd_text])
        else:
            parts.append(prd_text)
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("PRD input is required")
    return text, source


def _safe_prd_file(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("prd_file must be a safe relative path")
    if not path.exists() or not path.is_file():
        raise ValueError(f"prd_file not found: {value}")
    return path


def _input_prd_markdown(prd_text: str, source: str) -> str:
    return "\n".join(["# Input PRD", "", f"- Source: `{source}`", "", prd_text.strip(), ""]).rstrip() + "\n"


def _normalized_prd_markdown(redacted_prd: str, app_slug: str, generated_app_dir: str) -> str:
    title = _first_nonempty_line(redacted_prd)
    return "\n".join(
        [
            "# Normalized PRD",
            "",
            "## Business Goal",
            title or f"Generate local prototype app `{app_slug}` from the submitted PRD.",
            "",
            "## Target App",
            f"- App slug: `{app_slug}`",
            f"- Generated app dir: `{generated_app_dir}`",
            "- Frontend: native SPA",
            "- Backend: Node stdlib local server",
            "- Persistence: browser `localStorage`",
            "- Database: none",
            "",
            "## Source PRD Summary",
            _compact(redacted_prd, 1200),
            "",
            "## Scope Boundaries",
            "- Generate a local prototype app for PRD validation.",
            "- Do not create production deployment, database, credential collection, or hidden network calls.",
            "- Represent unavailable external integrations with local mock data, assumptions, or blockers.",
            "",
            "## Required States",
            "- Empty state",
            "- Loading state",
            "- Error or blocked state",
            "- Success state",
            "",
            "## Assumptions",
            "- v1 uses a native SPA and Node stdlib server with no package installation.",
            "- Human review is required before applying generated code to the main workspace.",
        ]
    ).rstrip() + "\n"


def _app_contract(
    *,
    app_slug: str,
    generated_app_dir: str,
    preview_url: str,
    verification_commands: list[str],
    quality_mode: str = "prototype",
    benchmark_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "app_slug": app_slug,
        "generated_at": now_iso(),
        "quality_mode": quality_mode,
        **({"benchmark_id": benchmark_context.get("benchmark_id")} if benchmark_context else {}),
        "target_stack": {
            "frontend": "native_spa",
            "backend": "node_stdlib",
            "storage": "localStorage",
            "database": "none",
        },
        "generated_app_dir": generated_app_dir,
        "required_files": [
            "server.js",
            "runtime_smoke.js",
            "public/index.html",
            "public/styles.css",
            "public/app.js",
            "README.md",
        ],
        "preview": {
            "command": "node server.js",
            "url": preview_url,
        },
        "verification_commands": verification_commands,
        "constraints": [
            "no database",
            "no external deploy",
            "localStorage only",
            "no secret persistence",
            "no hidden network calls",
        ],
        **(
            {
                "benchmark_parity": {
                    "reference_app_role": "capability_baseline",
                    "required_capability_ids": [item["id"] for item in benchmark_context.get("required_capabilities", [])],
                }
            }
            if benchmark_context
            else {}
        ),
    }


def _load_benchmark_context(source: str) -> dict[str, Any] | None:
    prefix = "prd_file:"
    if not source.startswith(prefix):
        return None
    prd_path = Path(source[len(prefix) :])
    parts = prd_path.parts
    if len(parts) < 4 or parts[0] != "benchmarks" or parts[1] != "app_generation" or prd_path.name != "input_prd.md":
        return None
    benchmark_dir = prd_path.parent
    required = ["benchmark.yaml", "acceptance_criteria.md", "expected_capabilities.json", "scoring_rubric.json"]
    if not all((benchmark_dir / name).exists() for name in required):
        return None
    manifest = load_yaml_subset(benchmark_dir / "benchmark.yaml")
    capabilities = read_json(benchmark_dir / "expected_capabilities.json")
    rubric = read_json(benchmark_dir / "scoring_rubric.json")
    acceptance_text = (benchmark_dir / "acceptance_criteria.md").read_text(encoding="utf-8")
    product_capabilities = capabilities.get("product_capabilities", []) if isinstance(capabilities, dict) else []
    required_capabilities = [item for item in product_capabilities if isinstance(item, dict) and item.get("required")]
    return {
        "schema_version": 1,
        "quality_mode": "benchmark_parity",
        "benchmark_id": manifest.get("benchmark_id") or capabilities.get("benchmark_id") or benchmark_dir.name,
        "benchmark_dir": str(benchmark_dir),
        "reference_app_dir": str(benchmark_dir / "reference_app"),
        "reference_app_role": "capability_baseline",
        "required_capabilities": required_capabilities,
        "runtime_expectations": capabilities.get("runtime_expectations", {}),
        "safety_expectations": capabilities.get("safety_expectations", {}),
        "hard_gates": rubric.get("hard_gates", []),
        "benchmark_specific_checks": rubric.get("benchmark_specific_checks", []),
        "acceptance_criteria_excerpt": _compact(acceptance_text, 1800),
        "instructions": [
            "Benchmark Parity mode is active.",
            "Generated app may use a different file structure, but must cover the reference_app core user capabilities.",
            "Do not replace required image upload, image generation, or image download paths with mock-only placeholders.",
            "Image providers must be explicit, server-side, and configured through placeholders or local environment only.",
            "Provider setup failures must be visible to users and must not persist secrets.",
            "For OpenRouter image generation, use POST https://openrouter.ai/api/v1/images with input_references; do not use chat/completions plus modalities as the image path.",
            "Use openai/gpt-5.4-image-2 as the default OpenRouter image model when OPENROUTER_IMAGE_MODEL is empty.",
            "Local iteration must understand 第 X 张第 Y 层, update the targeted prompt layer, show visible feedback, and mark that image for regeneration.",
        ],
    }


def _benchmark_context_markdown(context: dict[str, Any]) -> str:
    capabilities = context.get("required_capabilities", [])
    lines = [
        "# Benchmark Context",
        "",
        "## Benchmark Parity",
        "",
        f"- Benchmark: `{context.get('benchmark_id', '')}`",
        f"- Reference app role: `{context.get('reference_app_role', '')}`",
        f"- Reference app dir: `{context.get('reference_app_dir', '')}`",
        "",
        "## Required Capabilities",
    ]
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        capability_id = item.get("id", "")
        label = item.get("label", capability_id)
        required = bool(item.get("required"))
        lines.append(f"- `{capability_id}`: {label}" + (" (required)" if required else ""))
        for key in ("expected_behavior", "forbidden_behavior"):
            value = item.get(key)
            if value:
                lines.append(f"  - {key}: {value}")
        expected_values = item.get("expected_values")
        if isinstance(expected_values, list) and expected_values:
            lines.append(f"  - expected_values: {', '.join(str(v) for v in expected_values)}")
        for key in ("expected_count", "minimum_layers"):
            value = item.get(key)
            if value is not None:
                lines.append(f"  - {key}: {value}")
        evidence = item.get("evidence")
        if isinstance(evidence, list) and evidence:
            lines.append(f"  - evidence: {', '.join(str(v) for v in evidence[:3])}")
        detection = item.get("detection")
        if isinstance(detection, dict):
            match_any = detection.get("match_any")
            if isinstance(match_any, list) and match_any:
                lines.append(f"  - detection.match_any: {', '.join(str(v) for v in match_any[:5])}")
            evidence_files = detection.get("evidence_files")
            if isinstance(evidence_files, list) and evidence_files:
                lines.append(f"  - detection.evidence_files: {', '.join(str(v) for v in evidence_files)}")
    lines.extend(["", "## Instructions"])
    lines.extend(f"- {item}" for item in context.get("instructions", []))
    lines.extend(["", "## Acceptance Criteria Excerpt", "", str(context.get("acceptance_criteria_excerpt", ""))])
    return "\n".join(lines).rstrip() + "\n"


def evaluate_benchmark_parity(
    *,
    run_dir: Path,
    worktree_dir: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    benchmark_path = Path(run_dir) / "benchmark_context.json"
    if not benchmark_path.exists():
        return {"enabled": False, "blocking_events": [], "warnings": [], "artifacts": []}
    benchmark_context = read_json(benchmark_path)
    generated_app_dir = str(contract.get("generated_app_dir", ""))
    app_dir = Path(worktree_dir) / generated_app_dir
    required = [item for item in benchmark_context.get("required_capabilities", []) if isinstance(item, dict)]
    combined_text = _combined_generated_app_text(app_dir)
    per_file_text = _per_file_generated_app_text(app_dir)
    coverage: list[dict[str, Any]] = []
    missing: list[str] = []
    warnings: list[str] = []
    placeholder_allow = _collect_placeholders_allowed(required)
    for item in required:
        capability_id = str(item.get("id", ""))
        status = _capability_status(capability_id, combined_text, capability=item, per_file_text=per_file_text)
        coverage.append(
            {
                "id": capability_id,
                "label": item.get("label", capability_id),
                "required": True,
                "status": status,
                "evidence": _capability_evidence(capability_id, capability=item),
            }
        )
        if status == "missing":
            missing.append(capability_id)
    if not app_dir.exists():
        missing.append("generated_app_dir")
    secret_hits = _secret_hits(combined_text, placeholders_allowed=placeholder_allow)
    if secret_hits:
        missing.append("secret_leak")
    missing.extend(_benchmark_protocol_missing(combined_text))
    blocking_events = [f"benchmark_parity_missing:{item}" for item in _dedupe(missing)]
    score_payload = _benchmark_score_payload(benchmark_context, coverage, blocking_events, warnings)
    diff_markdown = _benchmark_diff_markdown(benchmark_context, app_dir, coverage, blocking_events, warnings)
    write_json(Path(run_dir) / "agqs_score.json", score_payload)
    (Path(run_dir) / "benchmark_diff.md").write_text(diff_markdown, encoding="utf-8")
    return {
        "enabled": True,
        "benchmark_id": benchmark_context.get("benchmark_id", ""),
        "blocking_events": blocking_events,
        "warnings": warnings,
        "artifacts": ["benchmark_diff.md", "agqs_score.json"],
        "coverage": coverage,
    }


def _combined_generated_app_text(app_dir: Path) -> str:
    if not app_dir.exists():
        return ""
    parts: list[str] = []
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or path.name == ".env" or "node_modules" in path.parts:
            continue
        if path.suffix.lower() not in {".js", ".html", ".css", ".json", ".md", ".example"} and path.name != ".env.example":
            continue
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _per_file_generated_app_text(app_dir: Path) -> dict[str, str]:
    if not app_dir.exists():
        return {}
    result: dict[str, str] = {}
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or path.name == ".env" or "node_modules" in path.parts:
            continue
        if path.suffix.lower() not in {".js", ".html", ".css", ".json", ".md", ".example"} and path.name != ".env.example":
            continue
        rel = path.relative_to(app_dir).as_posix()
        result[rel] = path.read_text(encoding="utf-8", errors="replace")
    return result


def _collect_placeholders_allowed(capabilities: list[dict[str, Any]]) -> list[str]:
    allowed: list[str] = []
    for item in capabilities:
        detection = item.get("detection") if isinstance(item, dict) else None
        if not isinstance(detection, dict):
            continue
        for value in detection.get("placeholders_allowed", []) or []:
            text = str(value).strip().lower()
            if text and text not in allowed:
                allowed.append(text)
    return allowed


def _file_matches_scope(rel: str, scopes: list[str]) -> bool:
    if not scopes:
        return True
    import fnmatch

    for scope in scopes:
        if fnmatch.fnmatch(rel, scope):
            return True
    return False


def _capability_status(
    capability_id: str,
    combined_text: str,
    *,
    capability: dict[str, Any] | None = None,
    per_file_text: dict[str, str] | None = None,
) -> str:
    metadata_match_any: list[str] = []
    evidence_files: list[str] = []
    if isinstance(capability, dict):
        detection = capability.get("detection") if isinstance(capability.get("detection"), dict) else {}
        metadata_match_any = [str(v).lower() for v in (detection.get("match_any") or []) if str(v).strip()]
        evidence_files = [str(v) for v in (detection.get("evidence_files") or []) if str(v).strip()]
    if metadata_match_any:
        if evidence_files and per_file_text is not None:
            for rel, text in per_file_text.items():
                if not _file_matches_scope(rel, evidence_files):
                    continue
                lowered = text.lower()
                if any(token in lowered for token in metadata_match_any):
                    return "covered"
            return "missing"
        normalized = combined_text.lower()
        return "covered" if any(token in normalized for token in metadata_match_any) else "missing"

    normalized = combined_text.lower().replace("'", "\"")
    if capability_id == "reference_image_upload":
        return "covered" if normalized.count("type=\"file\"") >= 2 and ("referenceimage" in normalized or "参考图" in combined_text) else "missing"
    if capability_id == "image_provider_proxy":
        has_endpoint = "/api/images/generate" in normalized
        has_provider = "openai" in normalized or "openrouter" in normalized
        return "covered" if has_endpoint and has_provider else "missing"
    if capability_id == "single_image_generation":
        has_generate_action = any(pattern in normalized for pattern in ("generateimage(", "generate-single", "generateone", "data-action=\"generate\""))
        has_single_copy = "单张" in combined_text or "single image" in normalized
        return "covered" if has_generate_action or ("/api/images/generate" in normalized and has_single_copy) else "missing"
    if capability_id == "batch_image_generation":
        has_batch_action = any(pattern in normalized for pattern in ("batchgenerate(", "batch-generate", "generateall", "生成全部", "批量"))
        has_generation_loop = "generateimage(" in normalized or "/api/images/generate" in normalized
        return "covered" if has_batch_action and has_generation_loop else "missing"
    if capability_id == "provider_setup_error":
        has_provider = "provider" in normalized
        has_setup_error = any(pattern in normalized for pattern in ("provider_not_configured", "not configured", "未配置", "setup error", "未设置", "未找到"))
        return "covered" if has_provider and has_setup_error else "missing"
    patterns = BENCHMARK_CAPABILITY_PATTERNS.get(capability_id)
    if not patterns:
        return "needs_manual_review"
    return "covered" if all(pattern.lower() in normalized for pattern in patterns) else "missing"


def _capability_evidence(
    capability_id: str,
    *,
    capability: dict[str, Any] | None = None,
) -> list[str]:
    if isinstance(capability, dict):
        detection = capability.get("detection") if isinstance(capability.get("detection"), dict) else {}
        match_any = [str(v) for v in (detection.get("match_any") or []) if str(v).strip()]
        if match_any:
            return match_any
    patterns = BENCHMARK_CAPABILITY_PATTERNS.get(capability_id)
    return list(patterns or ["manual_review"])


def _benchmark_protocol_missing(combined_text: str) -> list[str]:
    normalized = combined_text.lower()
    missing: list[str] = []
    if "openrouter" in normalized:
        if "chat/completions" in normalized and "modalities" in normalized:
            missing.append("openrouter_images_endpoint")
        has_images_endpoint = "/api/v1/images" in normalized or (
            "/api/v1" in normalized and "/images" in normalized and "openrouter_api_base_url" in normalized
        )
        if not has_images_endpoint or "input_references" not in normalized:
            missing.append("openrouter_images_endpoint")
    return _dedupe(missing)


def _secret_hits(
    text: str,
    *,
    placeholders_allowed: list[str] | None = None,
) -> list[str]:
    allow = [item.lower() for item in (placeholders_allowed or []) if str(item).strip()]
    hits: list[str] = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in PLACEHOLDER_SECRET_MARKERS):
            continue
        if any(token in lowered for token in allow):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(line):
                hits.append(pattern.pattern)
    return hits


def _benchmark_score_payload(
    benchmark_context: dict[str, Any],
    coverage: list[dict[str, Any]],
    blocking_events: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    covered = sum(1 for item in coverage if item.get("status") == "covered")
    total = len(coverage) or 1
    score = round((covered / total) * 100, 2)
    return {
        "schema_version": 1,
        "benchmark_id": benchmark_context.get("benchmark_id", ""),
        "overall_agqs": score,
        "score_source": "deterministic_static_parity_v1",
        "hard_gate_status": "failed" if blocking_events else "passed",
        "capability_coverage": coverage,
        "blocking_events": blocking_events,
        "warnings": warnings,
        "needs_manual_review": [
            "image quality",
            "reference image understanding",
            "platform strategy fit",
            "visual composition quality",
        ],
    }


def _benchmark_diff_markdown(
    benchmark_context: dict[str, Any],
    app_dir: Path,
    coverage: list[dict[str, Any]],
    blocking_events: list[str],
    warnings: list[str],
) -> str:
    lines = [
        "# Benchmark Diff",
        "",
        f"- Benchmark: `{benchmark_context.get('benchmark_id', '')}`",
        f"- Generated app: `{app_dir}`",
        f"- Status: {'failed' if blocking_events else 'passed'}",
        "",
        "## Capability Coverage",
        "",
    ]
    for item in coverage:
        lines.append(f"- {item.get('status')}: `{item.get('id')}` {item.get('label', '')}")
    lines.extend(["", "## Blocking Events"])
    lines.extend(f"- {item}" for item in blocking_events or ["None"])
    lines.extend(["", "## Warnings"])
    lines.extend(f"- {item}" for item in warnings or ["None"])
    return "\n".join(lines).rstrip() + "\n"


def _preview_instructions(contract: dict[str, Any]) -> str:
    generated_app_dir = str(contract.get("generated_app_dir", ""))
    preview = contract.get("preview") if isinstance(contract.get("preview"), dict) else {}
    command = str(preview.get("command", "node server.js"))
    url = str(preview.get("url", "http://127.0.0.1:8788"))
    return "\n".join(
        [
            "# Preview Instructions",
            "",
            "This is the planned local preview contract for the generated app.",
            "",
            "```bash",
            f"cd {generated_app_dir}",
            command,
            "```",
            "",
            f"Open `{url}` after the local server starts.",
            "",
            "The app must remain local-only and must not require a database or external service.",
        ]
    ).rstrip() + "\n"


def _first_nonempty_line(value: str) -> str:
    for line in value.splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            return text
    return ""


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _is_image_generation_prd(prd_text: str) -> bool:
    """检测 PRD 是否属于图片生成类（见 docs/app_generation_prd_to_local_app_spec.md § 图片生成类 PRD 要求）。

    触发条件：PRD 明确要求图片生成、主图生成、参考图出图、生图、模型选择或 OpenAI/OpenRouter 图片能力。
    """
    if not prd_text:
        return False
    haystack = prd_text.lower()
    chinese_triggers = ("图片生成", "主图生成", "参考图出图", "生图", "出图", "图片模型")
    english_triggers = (
        "image generation",
        "image generate",
        "generate image",
        "image model",
        "openrouter image",
        "openai image",
        "/api/images",
        "gpt-image",
        "dall-e",
    )
    for kw in chinese_triggers:
        if kw in prd_text:
            return True
    for kw in english_triggers:
        if kw in haystack:
            return True
    return False


def generate_deterministic_app_files(
    *,
    run_dir: Path,
    app_slug: str,
    prd_text: str,
    contract: dict[str, Any],
    repo_root: Path = Path("."),
) -> list[str]:
    """Generate a minimal runnable SPA template in deterministic mode.
    
    Returns:
        List of relative file paths created (e.g., ['generated_apps/todo/server.js', ...])
    """
    generated_app_dir = str(contract.get("generated_app_dir", f"generated_apps/{app_slug}"))
    preview = contract.get("preview") if isinstance(contract.get("preview"), dict) else {}
    preview_url = str(preview.get("url", "http://127.0.0.1:8788"))
    
    # Extract port from preview URL (e.g., "http://127.0.0.1:8788" -> 8788)
    port = 8788
    if ":" in preview_url:
        try:
            port = int(preview_url.rsplit(":", 1)[-1].rstrip("/"))
        except ValueError:
            pass
    
    # Extract title from PRD first line
    title = _first_nonempty_line(prd_text) or app_slug
    
    # Extract PRD summary (first paragraph or 200 chars)
    prd_summary = _compact(prd_text, 200)
    
    app_dir = repo_root / generated_app_dir
    public_dir = app_dir / "public"
    ensure_dir(public_dir)
    
    if _is_image_generation_prd(prd_text):
        return _generate_image_app_files(
            app_dir=app_dir,
            public_dir=public_dir,
            generated_app_dir=generated_app_dir,
            app_slug=app_slug,
            title=title,
            prd_summary=prd_summary,
            port=port,
        )
    
    # server.js - Node stdlib HTTP server
    server_js = f"""const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.env.PREVIEW_PORT || '{port}', 10);
const HOST = '127.0.0.1';
const PUBLIC_DIR = path.join(__dirname, 'public');

const MIME_TYPES = {{
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
}};

const server = http.createServer((req, res) => {{
  let filePath = req.url === '/' ? '/index.html' : req.url;
  filePath = path.join(PUBLIC_DIR, filePath);
  
  const ext = path.extname(filePath);
  const mimeType = MIME_TYPES[ext] || 'application/octet-stream';
  
  fs.readFile(filePath, (err, data) => {{
    if (err) {{
      res.statusCode = 404;
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      res.end('404 Not Found');
      return;
    }}
    res.statusCode = 200;
    res.setHeader('Content-Type', mimeType);
    res.end(data);
  }});
}});

server.listen(PORT, HOST, () => {{
  console.log(`Server running at http://${{HOST}}:${{PORT}}/`);
}});
"""
    
    # index.html
    index_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div id="app"></div>
  <script src="app.js"></script>
</body>
</html>
"""
    
    # styles.css
    styles_css = """* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
  color: #1d252c;
  background: #f6f7f9;
  padding: 24px;
}

.container {
  max-width: 800px;
  margin: 0 auto;
  background: #ffffff;
  border: 1px solid #dce2e7;
  border-radius: 8px;
  padding: 24px;
}

.card {
  background: #ffffff;
  border: 1px solid #dce2e7;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

input, button, select {
  font-family: inherit;
  font-size: 14px;
  padding: 8px 12px;
  border: 1px solid #dce2e7;
  border-radius: 6px;
}

button {
  background: #1f5d8c;
  color: #ffffff;
  cursor: pointer;
  border: none;
  padding: 10px 16px;
}

button:hover {
  background: #17496e;
}

.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: #667684;
}

.loading {
  text-align: center;
  padding: 24px;
  color: #2764ad;
}

.error {
  background: #fef2f2;
  border: 1px solid #fca5a5;
  border-radius: 6px;
  padding: 12px;
  color: #b43b3b;
  margin-bottom: 16px;
}

.item-list {
  list-style: none;
}

.item {
  padding: 12px;
  border-bottom: 1px solid #f2f5f7;
}

.item:last-child {
  border-bottom: none;
}
"""
    
    # app.js
    app_js = f"""const STATE_KEY = '{app_slug}-state';

// Load state from localStorage
let state = [];
try {{
  const stored = localStorage.getItem(STATE_KEY);
  if (stored) {{
    state = JSON.parse(stored);
  }}
}} catch (e) {{
  console.error('Failed to load state:', e);
}}

// Save state to localStorage
function saveState() {{
  try {{
    localStorage.setItem(STATE_KEY, JSON.stringify(state));
  }} catch (e) {{
    console.error('Failed to save state:', e);
  }}
}}

// Render functions
function renderEmpty() {{
  return `
    <div class="empty-state">
      <h2>空状态</h2>
      <p>暂无数据</p>
    </div>
  `;
}}

function renderLoading() {{
  return `
    <div class="loading">
      <p>加载中...</p>
    </div>
  `;
}}

function renderError(message) {{
  return `
    <div class="error">
      <strong>错误：</strong> ${{message}}
    </div>
  `;
}}

function renderSuccess(data) {{
  return `
    <div class="container">
      <h1>{title}</h1>
      <div class="card">
        <p>应用已加载</p>
        <p>数据项数：${{Array.isArray(data) ? data.length : 0}}</p>
      </div>
    </div>
  `;
}}

// Main render
function render() {{
  const app = document.getElementById('app');
  if (!app) return;
  
  if (Array.isArray(state) && state.length === 0) {{
    app.innerHTML = renderEmpty();
  }} else {{
    app.innerHTML = renderSuccess(state);
  }}
}}

// Expose for debugging
window.app = {{
  state,
  render,
  saveState,
}};

// Initial render
render();
"""
    
    # README.md
    readme = f"""# {app_slug}

Generated by Agent Team Runtime (deterministic fallback).

## Run Locally

```bash
node server.js
```

Open http://127.0.0.1:{port} in your browser.

## PRD Summary

{prd_summary}
"""
    
    # Write files
    (app_dir / "server.js").write_text(server_js, encoding="utf-8")
    (app_dir / "README.md").write_text(readme, encoding="utf-8")
    (public_dir / "index.html").write_text(index_html, encoding="utf-8")
    (public_dir / "styles.css").write_text(styles_css, encoding="utf-8")
    (public_dir / "app.js").write_text(app_js, encoding="utf-8")
    
    # Return relative paths
    return [
        f"{generated_app_dir}/server.js",
        f"{generated_app_dir}/README.md",
        f"{generated_app_dir}/public/index.html",
        f"{generated_app_dir}/public/styles.css",
        f"{generated_app_dir}/public/app.js",
    ]


def _generate_image_app_files(
    *,
    app_dir: Path,
    public_dir: Path,
    generated_app_dir: str,
    app_slug: str,
    title: str,
    prd_summary: str,
    port: int,
) -> list[str]:
    """生成图片生成类应用的完整脚手架（见 docs/app_generation_prd_to_local_app_spec.md § 图片生成类 PRD 要求）。
    
    包含：
    - GET /api/health + POST /api/images/generate（server.js）
    - provider 配置状态徽标 + 模型选择（index.html）
    - fetchHealth + callImageModel（app.js）
    - AGENT_EDIT 锚点（便于 patch_app）
    - .env.example（占位 key，无真实 secret）
    - README 配置段（明确说明在服务端 .env 配置 API_KEY）
    
    禁止：
    - 前端 API_KEY 输入框
    - localStorage 保存 key
    - config.json 持久化 key
    """
    # server.js - 包含 GET /api/health + POST /api/images/generate
    server_js = f"""const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = parseInt(process.env.PREVIEW_PORT || '{port}', 10);
const HOST = '127.0.0.1';
const PUBLIC_DIR = path.join(__dirname, 'public');

const MIME_TYPES = {{
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
}};

// === AGENT_EDIT:api-routes START ===
// GET /api/health - 返回 provider 配置状态
function handleHealthCheck(req, res) {{
  const openrouterKey = process.env.OPENROUTER_API_KEY;
  const openaiKey = process.env.OPENAI_API_KEY;
  const configured = !!(openrouterKey || openaiKey);
  const provider = openrouterKey ? 'openrouter' : (openaiKey ? 'openai' : 'none');
  const model = process.env.OPENROUTER_IMAGE_MODEL || process.env.OPENAI_IMAGE_MODEL || 'openai/gpt-5.4-image-2';
  
  res.statusCode = 200;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify({{
    provider,
    configured,
    model,
    message: configured ? '已配置' : '未配置：请在服务端 .env 配置 OPENROUTER_API_KEY 或 OPENAI_API_KEY'
  }}));
}}

// POST /api/images/generate - 从 process.env 读 API_KEY，调用外部图片 provider
function handleImageGenerate(req, res) {{
  const openrouterKey = process.env.OPENROUTER_API_KEY;
  const openaiKey = process.env.OPENAI_API_KEY;
  
  if (!openrouterKey && !openaiKey) {{
    res.statusCode = 422;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.end(JSON.stringify({{
      error: 'provider_not_configured',
      hint: '请在服务端 .env 配置 OPENROUTER_API_KEY 或 OPENAI_API_KEY 后重启'
    }}));
    return;
  }}
  
  let body = '';
  req.on('data', chunk => {{ body += chunk.toString(); }});
  req.on('end', () => {{
    let payload;
    try {{
      payload = JSON.parse(body);
    }} catch (e) {{
      res.statusCode = 400;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(JSON.stringify({{ error: 'invalid_json' }}));
      return;
    }}
    
    const model = payload.model || process.env.OPENROUTER_IMAGE_MODEL || 'openai/gpt-5.4-image-2';
    const prompt = payload.prompt || '生成一张商业主图';
    
    // 调用 OpenRouter /api/v1/images（OpenRouter 图片协议，见 docs/prd_to_local_app_spec.md）
    const apiUrl = 'https://openrouter.ai/api/v1/images';
    const apiKey = openrouterKey || openaiKey;
    
    const requestBody = JSON.stringify({{
      model,
      prompt,
      n: 1,
    }});
    
    const parsedUrl = new url.URL(apiUrl);
    const options = {{
      hostname: parsedUrl.hostname,
      port: parsedUrl.port || 443,
      path: parsedUrl.pathname,
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${{apiKey}}`,
        'Content-Length': Buffer.byteLength(requestBody)
      }}
    }};
    
    const proxyReq = https.request(options, proxyRes => {{
      let responseBody = '';
      proxyRes.on('data', chunk => {{ responseBody += chunk.toString(); }});
      proxyRes.on('end', () => {{
        res.statusCode = proxyRes.statusCode || 200;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(responseBody);
      }});
    }});
    
    proxyReq.on('error', err => {{
      res.statusCode = 502;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(JSON.stringify({{ error: 'provider_request_failed', message: err.message }}));
    }});
    
    proxyReq.write(requestBody);
    proxyReq.end();
  }});
}}
// === AGENT_EDIT:api-routes END ===

const server = http.createServer((req, res) => {{
  const pathname = url.parse(req.url || '/').pathname || '/';
  
  if (pathname === '/api/health' && req.method === 'GET') {{
    return handleHealthCheck(req, res);
  }}
  
  if (pathname === '/api/images/generate' && req.method === 'POST') {{
    return handleImageGenerate(req, res);
  }}
  
  // 静态文件服务
  let filePath = pathname === '/' ? '/index.html' : pathname;
  filePath = path.join(PUBLIC_DIR, filePath);
  
  const ext = path.extname(filePath);
  const mimeType = MIME_TYPES[ext] || 'application/octet-stream';
  
  fs.readFile(filePath, (err, data) => {{
    if (err) {{
      res.statusCode = 404;
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      res.end('404 Not Found');
      return;
    }}
    res.statusCode = 200;
    res.setHeader('Content-Type', mimeType);
    res.end(data);
  }});
}});

server.listen(PORT, HOST, () => {{
  console.log(`Server running at http://${{HOST}}:${{PORT}}/`);
}});
"""

    # index.html - 包含模型选择 + provider 配置状态徽标 + 生图按钮 + AGENT_EDIT 锚点
    index_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="container">
    <h1>{title}</h1>
    
    <!-- === AGENT_EDIT:provider-status START === -->
    <div class="status-bar">
      <span>Provider 状态：</span>
      <span id="provider-status" class="status-badge">检查中...</span>
      <span id="provider-model"></span>
    </div>
    <!-- === AGENT_EDIT:provider-status END === -->
    
    <!-- === AGENT_EDIT:model-selector START === -->
    <div class="card">
      <label for="model-select">选择模型：</label>
      <select id="model-select">
        <option value="openai/gpt-5.4-image-2">openai/gpt-5.4-image-2</option>
        <option value="openai/gpt-image-1">openai/gpt-image-1</option>
      </select>
    </div>
    <!-- === AGENT_EDIT:model-selector END === -->
    
    <!-- === AGENT_EDIT:prompt-input START === -->
    <div class="card">
      <label for="prompt-input">生图提示词：</label>
      <textarea id="prompt-input" rows="4" placeholder="描述你想生成的图片...">商业主图，白色背景，产品居中</textarea>
      <button id="generate-btn" class="primary">生成图片</button>
    </div>
    <!-- === AGENT_EDIT:prompt-input END === -->
    
    <div id="result-area"></div>
    <div id="error-area"></div>
  </div>
  <script src="app.js"></script>
</body>
</html>
"""

    # styles.css - 复用通用样式 + provider 状态徽标
    styles_css = """* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
  color: #1d252c;
  background: #f6f7f9;
  padding: 24px;
}

.container {
  max-width: 800px;
  margin: 0 auto;
  background: #ffffff;
  border: 1px solid #dce2e7;
  border-radius: 8px;
  padding: 24px;
}

.status-bar {
  margin-bottom: 16px;
  padding: 12px;
  background: #f2f5f7;
  border-radius: 6px;
  font-size: 14px;
}

.status-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.status-badge.configured {
  background: #d1f4e0;
  color: #0f5132;
}

.status-badge.not-configured {
  background: #fef2f2;
  color: #b43b3b;
}

.card {
  background: #ffffff;
  border: 1px solid #dce2e7;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
}

input, button, select, textarea {
  font-family: inherit;
  font-size: 14px;
  padding: 8px 12px;
  border: 1px solid #dce2e7;
  border-radius: 6px;
  width: 100%;
}

textarea {
  resize: vertical;
}

button {
  background: #1f5d8c;
  color: #ffffff;
  cursor: pointer;
  border: none;
  padding: 10px 16px;
  margin-top: 12px;
  width: auto;
}

button:hover {
  background: #17496e;
}

button.primary {
  background: #2764ad;
}

button.primary:hover {
  background: #1f5d8c;
}

.error {
  background: #fef2f2;
  border: 1px solid #fca5a5;
  border-radius: 6px;
  padding: 12px;
  color: #b43b3b;
  margin-bottom: 16px;
}

.loading {
  text-align: center;
  padding: 24px;
  color: #2764ad;
}

.image-result {
  margin-top: 16px;
  border: 1px solid #dce2e7;
  border-radius: 6px;
  overflow: hidden;
}

.image-result img {
  width: 100%;
  display: block;
}
"""

    # app.js - 包含 fetchHealth + callImageModel（localStorage 只保存模型选择，不保存 key）
    app_js = f"""const STATE_KEY = '{app_slug}-model';

// Load model selection from localStorage (NOT API_KEY)
let selectedModel = 'openai/gpt-5.4-image-2';
try {{
  const stored = localStorage.getItem(STATE_KEY);
  if (stored) {{
    selectedModel = stored;
  }}
}} catch (e) {{
  console.error('Failed to load model selection:', e);
}}

// Save model selection to localStorage (NOT API_KEY)
function saveModelSelection(model) {{
  try {{
    localStorage.setItem(STATE_KEY, model);
  }} catch (e) {{
    console.error('Failed to save model selection:', e);
  }}
}}

// Fetch provider health status
async function fetchHealth() {{
  try {{
    const res = await fetch('/api/health');
    const data = await res.json();
    
    const statusEl = document.getElementById('provider-status');
    const modelEl = document.getElementById('provider-model');
    
    if (data.configured) {{
      statusEl.textContent = data.message || '已配置';
      statusEl.className = 'status-badge configured';
      modelEl.textContent = `(当前模型: ${{data.model}})`;
    }} else {{
      statusEl.textContent = '未配置';
      statusEl.className = 'status-badge not-configured';
      modelEl.textContent = '请在服务端 .env 配置 API_KEY';
    }}
  }} catch (err) {{
    const statusEl = document.getElementById('provider-status');
    statusEl.textContent = '检查失败';
    statusEl.className = 'status-badge not-configured';
    console.error('Health check failed:', err);
  }}
}}

// Call image generation API
async function callImageModel(prompt, model) {{
  const resultArea = document.getElementById('result-area');
  const errorArea = document.getElementById('error-area');
  
  errorArea.innerHTML = '';
  resultArea.innerHTML = '<div class="loading">生成中...</div>';
  
  try {{
    const res = await fetch('/api/images/generate', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ prompt, model }})
    }});
    
    const data = await res.json();
    
    if (!res.ok) {{
      throw new Error(data.hint || data.error || 'Generation failed');
    }}
    
    // 假设返回 {{ data: [{{ url: "..." }}] }} 或类似结构
    if (data.data && data.data[0] && data.data[0].url) {{
      resultArea.innerHTML = `
        <div class="image-result">
          <img src="${{data.data[0].url}}" alt="Generated image" />
        </div>
      `;
    }} else {{
      resultArea.innerHTML = '<p>生成完成，但未返回图片 URL。</p>';
    }}
  }} catch (err) {{
    resultArea.innerHTML = '';
    errorArea.innerHTML = `<div class="error">${{err.message}}</div>`;
    console.error('Image generation failed:', err);
  }}
}}

// Initialize
document.addEventListener('DOMContentLoaded', () => {{
  fetchHealth();
  
  const modelSelect = document.getElementById('model-select');
  const generateBtn = document.getElementById('generate-btn');
  const promptInput = document.getElementById('prompt-input');
  
  if (modelSelect) {{
    modelSelect.value = selectedModel;
    modelSelect.addEventListener('change', (e) => {{
      selectedModel = e.target.value;
      saveModelSelection(selectedModel);
    }});
  }}
  
  if (generateBtn) {{
    generateBtn.addEventListener('click', () => {{
      const prompt = promptInput ? promptInput.value : '商业主图';
      callImageModel(prompt, selectedModel);
    }});
  }}
}});
"""

    # .env.example - 占位 key + 默认模型，无真实 secret
    env_example = """# OpenRouter API Key (推荐用于图片生成)
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# OpenRouter 图片模型（默认）
OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2

# 或使用 OpenAI 直连
# OPENAI_API_KEY=sk-your-openai-key-here
# OPENAI_IMAGE_MODEL=dall-e-3
"""

    # README - 包含「如何在服务端配置 API_KEY」段落
    readme = f"""# {app_slug}

Generated by Agent Team Runtime (deterministic fallback - image generation app).

## 功能

{prd_summary}

## 本地运行

1. 在当前目录创建 `.env` 文件，配置 API Key：

```bash
cp .env.example .env
# 编辑 .env，填入真实 OPENROUTER_API_KEY 或 OPENAI_API_KEY
```

2. 启动服务：

```bash
node server.js
```

3. 打开浏览器访问 http://127.0.0.1:{port}

## 如何在服务端配置 API_KEY

**重要：API Key 唯一配置来源是服务端 `.env` 或进程环境。**

前端不得要求用户输入 API Key，也不得把 API Key 写入 localStorage、URL 或日志。

### 方式 1：使用 `.env` 文件（推荐）

在生成应用目录下创建 `.env` 文件：

```dotenv
OPENROUTER_API_KEY=sk-or-v1-your-real-key-here
OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2
```

### 方式 2：启动前 export 环境变量

```bash
export OPENROUTER_API_KEY=sk-or-v1-your-real-key-here
export OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2
node server.js
```

### Provider 配置状态

启动后，页面顶部会显示 provider 配置状态：

- **已配置**：绿色徽标，可以正常生图
- **未配置**：红色徽标，提示「请在服务端 .env 配置 API_KEY」

前端只展示配置状态（已配置 / 未配置 / 错误），不显示 key 本身。

## 技术栈

- 前端：原生 SPA（无框架依赖）
- 后端：Node stdlib HTTP server
- 存储：localStorage（仅保存模型选择，不保存 API_KEY）
- API：GET /api/health + POST /api/images/generate

## OpenRouter 图片协议

本应用使用 OpenRouter `/api/v1/images` endpoint（见 docs/app_generation_prd_to_local_app_spec.md § OpenRouter 图片协议）。

禁止把 `chat/completions + modalities` 当作图片生成主路径。
"""

    # Write files
    (app_dir / "server.js").write_text(server_js, encoding="utf-8")
    (app_dir / "README.md").write_text(readme, encoding="utf-8")
    (app_dir / ".env.example").write_text(env_example, encoding="utf-8")
    (public_dir / "index.html").write_text(index_html, encoding="utf-8")
    (public_dir / "styles.css").write_text(styles_css, encoding="utf-8")
    (public_dir / "app.js").write_text(app_js, encoding="utf-8")
    
    # Return relative paths
    return [
        f"{generated_app_dir}/server.js",
        f"{generated_app_dir}/README.md",
        f"{generated_app_dir}/.env.example",
        f"{generated_app_dir}/public/index.html",
        f"{generated_app_dir}/public/styles.css",
        f"{generated_app_dir}/public/app.js",
    ]

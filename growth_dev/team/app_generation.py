from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
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

BUSINESS_FIELD_CANONICAL_NAMES = {
    "排名": "rank",
    "店铺名": "shop_name",
    "商品链接": "product_url",
    "商品主图": "product_image",
    "销量/支付买家数": "sales_or_pay_buyer_count",
    "GMV/交易指数": "gmv_or_transaction_index",
    "客单价": "price",
    "价格带": "price_band",
    "产品类型": "product_type",
    "材质": "material",
    "功能": "function",
    "风格": "style",
    "场景": "scene",
    "主卖点": "main_selling_point",
    "主图元素": "main_image_elements",
    "是否高增速": "growth_flag",
    "爆款原因": "hot_sale_reason",
}

REQUIRED_SKILL_SNAPSHOT_FILES = (
    "SKILL.md",
    "strategy_ir.yaml",
    "workflow.dag.yaml",
    "data_requirements.yaml",
    "tool_bindings.yaml",
    "output_schemas",
    "eval_rules.yaml",
    "evidence_schema.yaml",
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
    has_four_source_inputs = any(key in inputs for key in ("task_yaml_path", "domain_yaml_path", "skill_dir"))
    task_yaml_path = Path(str(inputs.get("task_yaml_path") or "tasks/current/task.yaml"))
    domain_yaml_path = Path(str(inputs.get("domain_yaml_path") or "tasks/current/domain.yaml"))
    skill_dir = Path(str(inputs.get("skill_dir") or ""))
    strategy_kb_config = _strategy_kb_config_from_inputs(inputs)
    data_capability_index = _prepare_api_doc_index_snapshot(run_dir, inputs)
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
    app_config: dict[str, Any] | None = None
    if has_four_source_inputs:
        skill_snapshot_dir = _prepare_app_generation_input_snapshot(
            run_dir=run_dir,
            task_yaml_path=task_yaml_path,
            domain_yaml_path=domain_yaml_path,
            skill_dir=skill_dir,
        )
        task_yaml = load_yaml_subset(run_dir / "input_task.yaml")
        domain_yaml = load_yaml_subset(run_dir / "input_domain.yaml")
        shell_kind_override = str(inputs.get("shell_kind") or "").strip() or None
        app_config = compile_app_config(
            skill_snapshot_dir=skill_snapshot_dir,
            task_yaml=task_yaml,
            domain_yaml=domain_yaml,
            prd_text=prd_text,
            app_slug=app_slug,
            shell_kind_override=shell_kind_override,
            strategy_kb_config=strategy_kb_config,
        )
        if data_capability_index:
            app_config["data_capability_index"] = data_capability_index
            _attach_api_doc_matching_to_nodes(app_config, data_capability_index)
        write_json(run_dir / "app.config.json", app_config)
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
        app_config=app_config,
    )
    if app_config:
        acceptance_criteria = derive_app_acceptance_criteria(app_config)
        contract["acceptance_criteria"] = acceptance_criteria
        (run_dir / "acceptance_criteria.md").write_text(_acceptance_criteria_markdown(acceptance_criteria), encoding="utf-8")
    write_json(run_dir / "app_contract.json", contract)
    (run_dir / "preview_instructions.md").write_text(_preview_instructions(contract), encoding="utf-8")
    output_paths = [
        "input_prd.md",
        "requirements/normalized_prd.md",
        "app_contract.json",
        "preview_instructions.md",
    ]
    if app_config:
        output_paths.extend(["input_task.yaml", "input_domain.yaml", "skill_snapshot/", "app.config.json", "acceptance_criteria.md"])
    if data_capability_index:
        output_paths.extend(["data_capability/api_doc_index.json", "data_capability/api_doc_index_report.md"])
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


def _prepare_app_generation_input_snapshot(
    *,
    run_dir: Path,
    task_yaml_path: Path,
    domain_yaml_path: Path,
    skill_dir: Path,
) -> Path:
    if not task_yaml_path.exists() or not task_yaml_path.is_file():
        raise ValueError(f"task_yaml_path not found: {task_yaml_path}")
    if not domain_yaml_path.exists() or not domain_yaml_path.is_file():
        raise ValueError(f"domain_yaml_path not found: {domain_yaml_path}")
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError(f"skill_dir not found: {skill_dir}")
    _validate_skill_snapshot_source(skill_dir)
    (run_dir / "input_task.yaml").write_text(task_yaml_path.read_text(encoding="utf-8"), encoding="utf-8")
    (run_dir / "input_domain.yaml").write_text(domain_yaml_path.read_text(encoding="utf-8"), encoding="utf-8")
    snapshot_dir = run_dir / "skill_snapshot"
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    shutil.copytree(skill_dir, snapshot_dir, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    _validate_skill_snapshot_source(snapshot_dir)
    return snapshot_dir


def _validate_skill_snapshot_source(skill_dir: Path) -> None:
    missing: list[str] = []
    for rel in REQUIRED_SKILL_SNAPSHOT_FILES:
        target = skill_dir / rel
        if not target.exists():
            missing.append(rel)
    output_schemas = skill_dir / "output_schemas"
    if output_schemas.exists() and output_schemas.is_dir() and not any(output_schemas.glob("*.json")):
        missing.append("output_schemas/*.json")
    if missing:
        raise ValueError(f"skill_snapshot missing required files: {', '.join(missing)}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _api_doc_index_stats(index_payload: dict[str, Any]) -> dict[str, int]:
    apis = index_payload.get("apis") if isinstance(index_payload.get("apis"), list) else []
    field_count = 0
    for api in apis:
        if isinstance(api, dict) and isinstance(api.get("response_fields"), list):
            field_count += len(api.get("response_fields", []))
    return {"api_count": len(apis), "field_count": field_count}


def _prepare_api_doc_index_snapshot(run_dir: Path, inputs: dict[str, Any]) -> dict[str, Any] | None:
    index_raw = str(inputs.get("api_doc_index") or "").strip()
    detail_raw = str(inputs.get("api_detail_doc") or "").strip()
    validation_raw = str(inputs.get("api_validation_doc") or "").strip()
    if not any((index_raw, detail_raw, validation_raw)):
        return None
    data_dir = ensure_dir(run_dir / "data_capability")
    index_path = data_dir / "api_doc_index.json"
    report_path = data_dir / "api_doc_index_report.md"
    sources: list[dict[str, Any]] = []
    build_mode = "prebuilt_index"
    if index_raw:
        source_index = Path(index_raw)
        if not source_index.exists() or not source_index.is_file():
            raise ValueError(f"api_doc_index not found: {source_index}")
        shutil.copy2(source_index, index_path)
        sources.append({
            "kind": "api_doc_index",
            "path": str(source_index),
            "sha256": _file_sha256(source_index),
        })
    else:
        if not detail_raw or not validation_raw:
            raise ValueError("api_detail_doc and api_validation_doc must be provided together")
        detail_path = Path(detail_raw)
        validation_path = Path(validation_raw)
        if not detail_path.exists() or not detail_path.is_file():
            raise ValueError(f"api_detail_doc not found: {detail_path}")
        if not validation_path.exists() or not validation_path.is_file():
            raise ValueError(f"api_validation_doc not found: {validation_path}")
        from api_doc_matcher.indexer import build_index

        build_mode = "built_from_docs"
        build_index(
            detail_markdown=detail_path.read_text(encoding="utf-8"),
            validation_markdown=validation_path.read_text(encoding="utf-8"),
            out_dir=data_dir,
            detail_source_path=str(detail_path),
            validation_source_path=str(validation_path),
        )
        sources.extend([
            {"kind": "api_detail_doc", "path": str(detail_path), "sha256": _file_sha256(detail_path)},
            {"kind": "api_validation_doc", "path": str(validation_path), "sha256": _file_sha256(validation_path)},
        ])
    index_payload = read_json(index_path)
    stats = _api_doc_index_stats(index_payload)
    report_path.write_text(
        "\n".join(
            [
                "# API Doc Index Snapshot",
                "",
                f"- provider: api_doc_index",
                f"- build_mode: {build_mode}",
                f"- api_count: {stats['api_count']}",
                f"- field_count: {stats['field_count']}",
                f"- source_index_ref: data_capability/api_doc_index.json",
                f"- runtime_index_ref: data/api_doc_index.json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "provider": "api_doc_index",
        "status": "available",
        "build_mode": build_mode,
        "source_index_ref": "data_capability/api_doc_index.json",
        "runtime_index_ref": "data/api_doc_index.json",
        "default_strategy": "field_coverage_rerank",
        "coverage_thresholds": {"workbench": 0.75, "default_mapping": 0.85},
        "stats": stats,
        "sources": sources,
    }


def _attach_api_doc_matching_to_nodes(config: dict[str, Any], data_capability_index: dict[str, Any]) -> None:
    nodes = config.get("nodes") if isinstance(config.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        output_fields = node.get("output_field_requirements") if isinstance(node.get("output_field_requirements"), list) else []
        data_mapping_context = node.get("data_mapping_context") if isinstance(node.get("data_mapping_context"), dict) else {}
        has_data_need = bool(node.get("data_requirements")) or bool(data_mapping_context.get("data_requirement_ids"))
        if not output_fields or not has_data_need:
            continue
        business_query = str(data_mapping_context.get("business_query") or node.get("name") or node.get("id") or "")
        data_mapping_context["api_doc_matching"] = {
            "enabled": True,
            "provider": "api_doc_index",
            "index_ref": str(data_capability_index.get("runtime_index_ref") or "data/api_doc_index.json"),
            "default_strategy": str(data_capability_index.get("default_strategy") or "field_coverage_rerank"),
            "candidate_strategies": ["title_only", "enriched_context", "field_coverage_rerank"],
            "business_query": business_query,
            "field_coverage_thresholds": data_capability_index.get("coverage_thresholds", {}),
            "derived_field_policy": {
                "mode": "agent_assisted",
                "requires_evidence": True,
                "requires_human_confirmation": True,
            },
        }
        node["data_mapping_context"] = data_mapping_context


def _strategy_kb_config_from_inputs(inputs: dict[str, Any]) -> dict[str, Any] | None:
    keys = ("strategy_kb", "strategy_kb_query_script", "strategy_kb_python", "strategy_kb_top_k")
    if not any(str(inputs.get(key) or "").strip() for key in keys):
        return None
    kb_path = Path(str(inputs.get("strategy_kb") or "").strip())
    query_script = Path(str(inputs.get("strategy_kb_query_script") or "").strip())
    if not str(kb_path):
        raise ValueError("strategy_kb is required when Strategy KB context is enabled")
    if not kb_path.exists() or not kb_path.is_file():
        raise ValueError(f"strategy_kb not found: {kb_path}")
    if not str(query_script):
        raise ValueError("strategy_kb_query_script is required when Strategy KB context is enabled")
    if not query_script.exists() or not query_script.is_file():
        raise ValueError(f"strategy_kb_query_script not found: {query_script}")
    try:
        top_k = int(inputs.get("strategy_kb_top_k") or 3)
    except (TypeError, ValueError) as exc:
        raise ValueError("strategy_kb_top_k must be an integer") from exc
    if top_k < 1:
        raise ValueError("strategy_kb_top_k must be >= 1")
    return {
        "kb": str(kb_path),
        "query_script": str(query_script),
        "python": str(inputs.get("strategy_kb_python") or "python3"),
        "top_k": top_k,
    }


def _strategy_kb_app_ref(strategy_kb_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not strategy_kb_config:
        return None
    return {
        "mode": "local-skills.strategy_kb_search",
        "kb_manifest": str(strategy_kb_config.get("kb") or ""),
        "query_script": str(strategy_kb_config.get("query_script") or ""),
        "top_k": int(strategy_kb_config.get("top_k") or 3),
    }


def compile_app_config(
    *,
    skill_snapshot_dir: Path,
    task_yaml: dict[str, Any],
    domain_yaml: dict[str, Any],
    prd_text: str,
    app_slug: str | None = None,
    shell_kind_override: str | None = None,
    strategy_kb_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile deterministic app.config.json from PRD + task + domain + skill artifacts."""
    skill_snapshot_dir = Path(skill_snapshot_dir)
    _validate_skill_snapshot_source(skill_snapshot_dir)
    workflow = _load_skill_yaml_subset(skill_snapshot_dir / "workflow.dag.yaml")
    data_requirements_yaml = _load_skill_yaml_subset(skill_snapshot_dir / "data_requirements.yaml")
    tool_bindings_yaml = _load_skill_yaml_subset(skill_snapshot_dir / "tool_bindings.yaml")
    eval_rules_yaml = _load_skill_yaml_subset(skill_snapshot_dir / "eval_rules.yaml")
    evidence_schema = _load_skill_yaml_subset(skill_snapshot_dir / "evidence_schema.yaml")
    data_requirements = _compile_data_requirements(data_requirements_yaml)
    tool_bindings = _compile_tool_bindings(tool_bindings_yaml)
    evidence_contract = _compile_evidence_contract(evidence_schema)
    nodes = _compile_app_config_nodes(
        workflow,
        skill_snapshot_dir,
        data_requirements=data_requirements,
        tool_bindings=tool_bindings,
        evidence_contract=evidence_contract,
        strategy_kb_config=strategy_kb_config,
    )
    shell_kind = str(
        (shell_kind_override or "").strip()
        or task_yaml.get("shell_kind")
        or domain_yaml.get("shell_kind")
        or "report_generator"
    )
    return {
        "schema_version": "app-config-v1",
        "app_slug": str(app_slug or task_yaml.get("task_id") or "generated-app"),
        "shell_kind": shell_kind,
        "shell_version": _shell_version(shell_kind),
        "skill_ref": {
            "skill_id": str(task_yaml.get("skill_id") or _read_skill_id(skill_snapshot_dir)),
            "snapshot_dir": "skill_snapshot",
        },
        "strategy_kb_ref": _strategy_kb_app_ref(strategy_kb_config),
        "task_ref": {
            "task_id": str(task_yaml.get("task_id") or ""),
            "title": str(task_yaml.get("title") or domain_yaml.get("title") or ""),
        },
        "scope_form": _compile_scope_form(task_yaml, domain_yaml),
        "nodes": nodes,
        "aggregate": _compile_aggregate(task_yaml, nodes),
        "data_requirements": data_requirements,
        "rules": {
            "hard_requirements": [{"id": str(item)} for item in eval_rules_yaml.get("hard_requirements", [])],
            "registry": _compile_rule_registry(eval_rules_yaml),
        },
        "tool_bindings": tool_bindings,
        "evidence": {"schema": evidence_schema, "contract": evidence_contract},
        "safety": {
            "risk_rules": list(domain_yaml.get("risk_rules", [])),
            "effective_tool_mode": "manual_upload_only",
            "forbidden": ["database", "secret_persistence", "real_ecommerce_api", "login_bypass"],
        },
        "customizations": _parse_prd_customizations(prd_text),
    }


def derive_app_acceptance_criteria(app_config: dict[str, Any]) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    for index, item in enumerate(app_config.get("customizations", []), start=1):
        if not isinstance(item, dict):
            continue
        criteria.append(
            {
                "id": f"AC-CUSTOM-{index:03d}",
                "source": "customizations",
                "description": str(item.get("acceptance") or ""),
                "location": str(item.get("location") or ""),
                "observable": True,
                "testable": True,
            }
        )
    for item in app_config.get("rules", {}).get("hard_requirements", []):
        requirement_id = str(item.get("id") if isinstance(item, dict) else item)
        criteria.append(
            {
                "id": f"AC-RULE-{requirement_id}",
                "source": "rules.hard_requirements",
                "description": _hard_requirement_description(requirement_id),
                "observable": True,
                "testable": True,
            }
        )
    for item in app_config.get("safety", {}).get("forbidden", []):
        criteria.append(
            {
                "id": f"AC-SAFETY-{str(item).replace('_', '-')}",
                "source": "safety",
                "description": f"Generated app must not use {item}.",
                "observable": True,
                "testable": True,
            }
        )
    for node in app_config.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        criteria.append(
            {
                "id": f"AC-NODE-{node_id}",
                "source": "nodes",
                "description": f"Node `{node_id}` exposes input, running, done, degraded, and failed states with auditable outputs.",
                "observable": True,
                "testable": True,
            }
        )
    return criteria


def _shell_version(shell_kind: str) -> str:
    if shell_kind != "report_generator":
        return ""
    version_path = Path("shells") / "report_generator" / "version.txt"
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()
    return "dev"


def validate_app_config(run_dir: Path) -> list[str]:
    run_dir = Path(run_dir)
    config_path = run_dir / "app.config.json"
    if not config_path.exists():
        return ["app.config.json missing"]
    config = read_json(config_path)
    errors: list[str] = []
    if config.get("schema_version") != "app-config-v1":
        errors.append("schema_version must be app-config-v1")
    if not config.get("app_slug"):
        errors.append("app_slug is required")
    if config.get("shell_kind") != "report_generator":
        errors.append("shell_kind must be report_generator")
    data_capability_index = config.get("data_capability_index")
    if data_capability_index is not None:
        if not isinstance(data_capability_index, dict):
            errors.append("data_capability_index must be an object")
        else:
            if data_capability_index.get("provider") != "api_doc_index":
                errors.append("data_capability_index provider must be api_doc_index")
            if data_capability_index.get("status") != "available":
                errors.append("data_capability_index status must be available")
            stats = data_capability_index.get("stats") if isinstance(data_capability_index.get("stats"), dict) else {}
            if not isinstance(stats.get("api_count"), int):
                errors.append("data_capability_index stats.api_count missing")
            if not isinstance(stats.get("field_count"), int):
                errors.append("data_capability_index stats.field_count missing")
            runtime_ref = str(data_capability_index.get("runtime_index_ref") or "")
            if runtime_ref and (".." in Path(runtime_ref).parts or Path(runtime_ref).is_absolute()):
                errors.append("data_capability_index runtime_index_ref must be relative and safe")
    if not isinstance(config.get("nodes"), list) or not config.get("nodes"):
        errors.append("nodes must be a non-empty list")
    if not isinstance(config.get("data_requirements"), list):
        errors.append("data_requirements must be a list")
    if any(item.get("effective_mode") != "manual_upload_only" for item in config.get("tool_bindings", []) if isinstance(item, dict)):
        errors.append("tool_bindings must be downgraded to manual_upload_only")
    for node in config.get("nodes", []):
        if not isinstance(node, dict):
            continue
        for field in ("input_model", "output_model", "execution_model", "evidence_model", "tool_model", "source_trace", "business_context", "node_execution_view"):
            if not isinstance(node.get(field), dict):
                errors.append(f"node {node.get('id', '')} missing {field}")
        business_context = node.get("business_context") if isinstance(node.get("business_context"), dict) else {}
        if business_context and business_context.get("status") not in {"available", "missing", "error"}:
            errors.append(f"node {node.get('id', '')} business_context status invalid")
        execution_view = node.get("node_execution_view") if isinstance(node.get("node_execution_view"), dict) else {}
        if execution_view and execution_view.get("status") not in {"available", "missing", "partial"}:
            errors.append(f"node {node.get('id', '')} node_execution_view status invalid")
        outputs = node.get("output_model", {}).get("outputs") if isinstance(node.get("output_model"), dict) else None
        if not isinstance(outputs, list) or not outputs:
            errors.append(f"node {node.get('id', '')} output_model.outputs missing")
        else:
            for output in outputs:
                if not isinstance(output, dict) or not isinstance(output.get("schema"), dict):
                    errors.append(f"node {node.get('id', '')} output model schema missing")
                elif output.get("summary", {}).get("status") != "available":
                    errors.append(f"node {node.get('id', '')} output model summary unavailable")
        if node.get("kind") == "data":
            required_data = node.get("input_model", {}).get("required_data") if isinstance(node.get("input_model"), dict) else None
            if not isinstance(required_data, list) or not required_data:
                errors.append(f"data node {node.get('id', '')} required_data missing")
            elif any(not isinstance(item, dict) for item in required_data):
                errors.append(f"data node {node.get('id', '')} required_data must be expanded objects")
        output_field_requirements = node.get("output_field_requirements")
        if not isinstance(output_field_requirements, list):
            errors.append(f"node {node.get('id', '')} output_field_requirements missing")
        elif outputs and not output_field_requirements:
            errors.append(f"node {node.get('id', '')} output_field_requirements empty")
        else:
            for requirement in output_field_requirements:
                if not isinstance(requirement, dict):
                    errors.append(f"node {node.get('id', '')} output_field_requirements must be objects")
                    continue
                for field in ("output_id", "field_path", "field_name", "title", "description", "type", "required", "source_schema_ref"):
                    if field not in requirement:
                        errors.append(f"node {node.get('id', '')} output_field_requirement missing {field}")
        data_mapping_context = node.get("data_mapping_context")
        if not isinstance(data_mapping_context, dict):
            errors.append(f"node {node.get('id', '')} data_mapping_context missing")
        elif output_field_requirements and data_mapping_context.get("output_field_count") != len(output_field_requirements):
            errors.append(f"node {node.get('id', '')} data_mapping_context output_field_count mismatch")
        tool_model = node.get("tool_model") if isinstance(node.get("tool_model"), dict) else {}
        if tool_model.get("effective_mode") != "manual_upload_only":
            errors.append(f"node {node.get('id', '')} tool_model effective_mode must be manual_upload_only")
        for schema in node.get("output_schema", []):
            if not isinstance(schema, dict):
                errors.append(f"invalid output_schema entry on node {node.get('id', '')}")
                continue
            schema_id = str(schema.get("id") or "")
            if schema.get("status") == "missing":
                errors.append(f"output schema missing: {schema_id}")
            if schema.get("summary", {}).get("status") != "available":
                errors.append(f"output schema summary unavailable: {schema_id}")
    evidence = config.get("evidence") if isinstance(config.get("evidence"), dict) else {}
    if not isinstance(evidence.get("contract"), dict):
        errors.append("evidence contract missing")
    elif not isinstance(evidence.get("contract", {}).get("required"), list):
        errors.append("evidence contract required fields missing")
    skill_eval = _load_skill_yaml_subset(run_dir / "skill_snapshot" / "eval_rules.yaml") if (run_dir / "skill_snapshot" / "eval_rules.yaml").exists() else {}
    expected_rules = {
        str(item.get("rule_id")): str(item.get("condition") or "")
        for item in skill_eval.get("rules", [])
        if isinstance(item, dict) and item.get("rule_id")
    }
    actual_rules = {
        str(item.get("rule_id")): str(item.get("condition") or "")
        for item in config.get("rules", {}).get("registry", [])
        if isinstance(item, dict) and item.get("rule_id")
    }
    for rule_id, condition in expected_rules.items():
        if actual_rules.get(rule_id) != condition:
            errors.append(f"rule registry drift: {rule_id}")
    expected_hard = [str(item) for item in skill_eval.get("hard_requirements", [])]
    actual_hard = [str(item.get("id")) for item in config.get("rules", {}).get("hard_requirements", []) if isinstance(item, dict)]
    if expected_hard and actual_hard != expected_hard:
        errors.append("hard_requirements drift from eval_rules.yaml")
    return errors


def validate_app_acceptance(run_dir: Path) -> list[str]:
    run_dir = Path(run_dir)
    config_path = run_dir / "app.config.json"
    contract_path = run_dir / "app_contract.json"
    markdown_path = run_dir / "acceptance_criteria.md"
    if not config_path.exists():
        return ["app.config.json missing"]
    if not contract_path.exists():
        return ["app_contract.json missing"]
    if not markdown_path.exists():
        return ["acceptance_criteria.md missing"]
    config = read_json(config_path)
    contract = read_json(contract_path)
    expected = derive_app_acceptance_criteria(config)
    actual = contract.get("acceptance_criteria") if isinstance(contract.get("acceptance_criteria"), list) else []
    expected_ids = [item["id"] for item in expected]
    actual_ids = [str(item.get("id")) for item in actual if isinstance(item, dict)]
    errors: list[str] = []
    if expected_ids != actual_ids:
        errors.append("acceptance_criteria does not match derived closure")
    markdown = markdown_path.read_text(encoding="utf-8")
    for criteria_id in expected_ids:
        if criteria_id not in markdown:
            errors.append(f"acceptance markdown missing {criteria_id}")
    return errors


def _hard_requirement_description(requirement_id: str) -> str:
    descriptions = {
        "required_outputs_present": "Every declared output schema appears in the final report.",
        "evidence_required_for_each_conclusion": "Every conclusion binds at least one evidence_id.",
        "score_formula_required": "Opportunity scores include formula output and never stand alone as unsupported conclusions.",
        "no_data_no_strong_claim": "When data is missing, the app shows degraded state instead of strong claims.",
    }
    return descriptions.get(requirement_id, requirement_id)


def _acceptance_criteria_markdown(criteria: list[dict[str, Any]]) -> str:
    lines = ["# Acceptance Criteria", ""]
    for item in criteria:
        lines.append(f"- `{item.get('id')}` ({item.get('source')}): {item.get('description')}")
    return "\n".join(lines).rstrip() + "\n"


def _compile_app_config_nodes(
    workflow: dict[str, Any],
    skill_snapshot_dir: Path,
    *,
    data_requirements: list[dict[str, Any]] | None = None,
    tool_bindings: list[dict[str, Any]] | None = None,
    evidence_contract: dict[str, Any] | None = None,
    strategy_kb_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    data_by_id = {str(item.get("id") or ""): item for item in data_requirements or [] if isinstance(item, dict)}
    bindings_by_requirement = {
        str(item.get("data_requirement_id") or ""): item
        for item in tool_bindings or []
        if isinstance(item, dict)
    }
    evidence = evidence_contract or {}
    nodes: list[dict[str, Any]] = []
    for index, item in enumerate(raw_nodes, start=1):
        if not isinstance(item, dict):
            continue
        outputs = [str(value) for value in item.get("outputs", [])]
        requirement_ids = [str(value) for value in item.get("data_requirements", [])]
        output_schemas = [_load_output_schema(skill_snapshot_dir, output_id) for output_id in outputs]
        required_data = [_node_required_data(requirement_id, data_by_id, bindings_by_requirement) for requirement_id in requirement_ids]
        node_kind = _node_kind(str(item.get("type") or ""))
        state_machine = ["idle", "waiting_input", "running", "done", "degraded", "failed"]
        business_context = _node_business_context(index, item, strategy_kb_config)
        if business_context.get("status") != "available":
            business_context = _strategy_ir_business_context(index, item, skill_snapshot_dir, business_context)
        output_model_outputs = [_node_output_model_item(schema_item) for schema_item in output_schemas if isinstance(schema_item, dict)]
        node_execution_view = _node_execution_view(index, item, business_context, output_model_outputs)
        output_field_requirements = _node_output_field_requirements(output_model_outputs, required_data, node_execution_view)
        nodes.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or item.get("id") or ""),
                "kind": node_kind,
                "source_type": str(item.get("type") or ""),
                "depends_on": [str(value) for value in item.get("depends_on", [])],
                "data_requirements": requirement_ids,
                "outputs": outputs,
                "output_schema": output_schemas,
                "output_field_requirements": output_field_requirements,
                "state_machine": state_machine,
                "input_model": _node_input_model(
                    node_kind,
                    required_data,
                    node_execution_view.get("action", {}).get("fields", [])
                    if isinstance(node_execution_view.get("action"), dict)
                    else [],
                ),
                "output_model": {"outputs": output_model_outputs},
                "execution_model": _node_execution_model(node_kind, state_machine, required_data),
                "evidence_model": {
                    "contract": evidence,
                    "required": [str(value) for value in evidence.get("required", [])] if isinstance(evidence.get("required"), list) else [],
                },
                "tool_model": _node_tool_model(required_data),
                "source_trace": _node_source_trace(requirement_ids, output_model_outputs, business_context),
                "business_context": business_context,
                "node_execution_view": node_execution_view,
                "data_mapping_context": _node_data_mapping_context(
                    item,
                    required_data,
                    output_model_outputs,
                    output_field_requirements,
                    business_context,
                    node_execution_view,
                ),
            }
        )
    return nodes


def _node_required_data(
    requirement_id: str,
    data_by_id: dict[str, dict[str, Any]],
    bindings_by_requirement: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = data_by_id.get(requirement_id)
    binding = bindings_by_requirement.get(requirement_id)
    if not source:
        return {
            "id": requirement_id,
            "status": "unresolved",
            "description": "",
            "required_fields": [],
            "freshness": "",
            "effective_mode": "manual_upload_only",
            "evidence_required": [],
            "preferred_sources": [],
            "fallback_sources": [],
            "tool_binding": _node_tool_binding(requirement_id, binding),
        }
    return {
        "id": str(source.get("id") or requirement_id),
        "status": "available",
        "description": str(source.get("description") or ""),
        "required_fields": [str(value) for value in source.get("required_fields", [])],
        "freshness": str(source.get("freshness") or ""),
        "effective_mode": "manual_upload_only",
        "evidence_required": [str(value) for value in source.get("evidence_required", [])],
        "preferred_sources": [str(value) for value in source.get("preferred_sources", [])],
        "fallback_sources": [str(value) for value in source.get("fallback_sources", [])],
        "tool_binding": _node_tool_binding(requirement_id, binding),
    }


def _node_tool_binding(requirement_id: str, binding: dict[str, Any] | None) -> dict[str, Any]:
    binding = binding or {}
    return {
        "data_requirement_id": requirement_id,
        "declared_primary_tool": str(binding.get("declared_primary_tool") or ""),
        "declared_fallback_tools": [str(value) for value in binding.get("declared_fallback_tools", [])],
        "effective_mode": "manual_upload_only",
        "status": "available" if binding else "unresolved",
    }


def _node_output_model_item(schema_item: dict[str, Any]) -> dict[str, Any]:
    summary = schema_item.get("summary") if isinstance(schema_item.get("summary"), dict) else {}
    schema = schema_item.get("schema") if isinstance(schema_item.get("schema"), dict) else {}
    return {
        "id": str(schema_item.get("id") or summary.get("id") or ""),
        "title": str(summary.get("title") or schema.get("title") or schema_item.get("id") or ""),
        "description": str(summary.get("description") or schema.get("description") or ""),
        "status": str(schema_item.get("status") or summary.get("status") or ""),
        "source": str(schema_item.get("source") or summary.get("source") or ""),
        "schema": schema,
        "summary": summary,
    }


def _node_output_field_requirements(
    output_items: list[dict[str, Any]],
    required_data: list[dict[str, Any]],
    node_execution_view: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    business_requirements = _business_doc_output_field_requirements(output_items, node_execution_view or {})
    if business_requirements:
        return business_requirements
    requirements: list[dict[str, Any]] = []
    for output in output_items:
        requirements.extend(_output_field_requirements_for_output(output))
    granular = [
        item
        for item in requirements
        if item.get("field_name") not in {"rows", "conclusions", "evidence_ids"}
    ]
    if granular:
        return requirements
    fallback_requirements: list[dict[str, Any]] = []
    fallback_output_id = str(output_items[0].get("id") or "node_output") if output_items else "node_output"
    fallback_title = str(output_items[0].get("title") or fallback_output_id) if output_items else fallback_output_id
    existing_names: set[str] = set()
    for data in required_data:
        fields = data.get("required_fields") if isinstance(data.get("required_fields"), list) else []
        for field in fields:
            field_name = str(field or "").strip()
            if not field_name or field_name in existing_names:
                continue
            existing_names.add(field_name)
            fallback_requirements.append(
                {
                    "output_id": fallback_output_id,
                    "field_path": f"items.properties.{field_name}",
                    "field_name": field_name,
                    "title": field_name,
                    "description": str(data.get("description") or fallback_title),
                    "canonical_field_name": field_name,
                    "type": "unknown",
                    "required": True,
                    "source_schema_ref": f"skill_snapshot/data_requirements.yaml#{data.get('id') or ''}.required_fields",
                    "source": "data_requirement_fallback",
                }
            )
    return fallback_requirements or requirements


def _business_doc_output_field_requirements(
    output_items: list[dict[str, Any]],
    node_execution_view: dict[str, Any],
) -> list[dict[str, Any]]:
    artifact = node_execution_view.get("artifact") if isinstance(node_execution_view.get("artifact"), dict) else {}
    markdown = str(artifact.get("markdown") or "")
    rows = _markdown_first_table_rows(markdown)
    if not rows:
        return []
    output_id = str(output_items[0].get("id") or "node_output") if output_items else "node_output"
    source = node_execution_view.get("source") if isinstance(node_execution_view.get("source"), dict) else {}
    source_trace = {
        "business_doc_ref": str(source.get("source_path") or ""),
        "citation_id": str(source.get("citation_id") or ""),
        "workflow_ref": str(source.get("heading") or node_execution_view.get("workflow_title") or ""),
        "source_line_start": int(source.get("source_line_start") or 0),
        "source_line_end": int(source.get("source_line_end") or 0),
    }
    requirements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        field_name = str(row.get("字段") or row.get("字段名") or row.get("名称") or "").strip()
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        description = str(row.get("说明") or row.get("填写要求") or row.get("描述") or "").strip()
        canonical = BUSINESS_FIELD_CANONICAL_NAMES.get(field_name) or _canonical_field_name(field_name)
        requirements.append(
            {
                "output_id": output_id,
                "field_path": f"items.properties.{canonical}",
                "field_name": field_name,
                "title": field_name,
                "description": description,
                "canonical_field_name": canonical,
                "type": "unknown",
                "required": True,
                "source_schema_ref": f"business_doc:{source_trace['workflow_ref']}#artifact_table",
                "source": "business_doc_output_table",
                "source_trace": source_trace,
            }
        )
    return requirements


def _canonical_field_name(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower()
    return normalized or f"field_{abs(hash(value)) % 100000}"


def _output_field_requirements_for_output(output: dict[str, Any]) -> list[dict[str, Any]]:
    schema = output.get("schema") if isinstance(output.get("schema"), dict) else {}
    output_id = str(output.get("id") or "")
    source_schema_ref = f"skill_snapshot/output_schemas/{output_id}.json" if output_id else "skill_snapshot/output_schemas"
    fields: list[dict[str, Any]] = []

    def append_properties(properties: dict[str, Any], required: list[str], prefix: str = "properties") -> None:
        for name, property_schema in properties.items():
            child = property_schema if isinstance(property_schema, dict) else {}
            field_name = str(name)
            fields.append(
                {
                    "output_id": output_id,
                    "field_path": f"{prefix}.{field_name}",
                    "field_name": field_name,
                    "title": str(child.get("title") or field_name),
                    "description": str(child.get("description") or child.get("desc") or ""),
                    "type": str(child.get("type") or "unknown"),
                    "required": field_name in required,
                    "source_schema_ref": source_schema_ref,
                    "source": "output_schema",
                }
            )

    if str(schema.get("type") or "") == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        properties = item_schema.get("properties") if isinstance(item_schema.get("properties"), dict) else {}
        required = [str(value) for value in item_schema.get("required", [])] if isinstance(item_schema.get("required"), list) else []
        append_properties(properties, required, "items.properties")
        return fields

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = [str(value) for value in schema.get("required", [])] if isinstance(schema.get("required"), list) else []
    append_properties(properties, required, "properties")
    for name, property_schema in properties.items():
        child = property_schema if isinstance(property_schema, dict) else {}
        if str(child.get("type") or "") != "array":
            continue
        item_schema = child.get("items") if isinstance(child.get("items"), dict) else {}
        item_properties = item_schema.get("properties") if isinstance(item_schema.get("properties"), dict) else {}
        if not item_properties:
            continue
        item_required = [str(value) for value in item_schema.get("required", [])] if isinstance(item_schema.get("required"), list) else []
        append_properties(item_properties, item_required, f"properties.{name}.items.properties")
    return fields


def _node_data_mapping_context(
    node: dict[str, Any],
    required_data: list[dict[str, Any]],
    output_items: list[dict[str, Any]],
    output_field_requirements: list[dict[str, Any]],
    business_context: dict[str, Any],
    node_execution_view: dict[str, Any],
) -> dict[str, Any]:
    upstream_artifacts = [str(value) for value in node.get("depends_on", [])]
    return {
        "status": "available" if output_field_requirements else "missing_output_fields",
        "business_context_ref": f"app.config.json:nodes.{node.get('id', '')}.business_context",
        "node_execution_view_ref": f"app.config.json:nodes.{node.get('id', '')}.node_execution_view",
        "source_context_refs": _node_data_mapping_source_refs(node, required_data, output_items),
        "data_requirement_ids": [str(item.get("id") or "") for item in required_data],
        "output_ids": [str(item.get("id") or "") for item in output_items],
        "output_field_count": len(output_field_requirements),
        "output_field_requirements": output_field_requirements,
        "multi_api_mapping": {
            "enabled": True,
            "requires_join_review": True,
            "allowed_fill_modes": ["api_field", "manual_fill", "derived", "not_available"],
        },
        "upstream_artifact_node_ids": upstream_artifacts,
        "business_query": str(business_context.get("query") or ""),
        "workflow_title": str(node_execution_view.get("workflow_title") or node.get("name") or node.get("id") or ""),
    }


def _node_data_mapping_source_refs(
    node: dict[str, Any],
    required_data: list[dict[str, Any]],
    output_items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    node_id = str(node.get("id") or "")
    refs = [
        {
            "kind": "node_execution_view",
            "ref": f"app.config.json:nodes.{node_id}.node_execution_view",
            "summary": "节点业务片段和执行动作",
        },
        {
            "kind": "business_context",
            "ref": f"app.config.json:nodes.{node_id}.business_context",
            "summary": "业务文档检索结果",
        },
    ]
    refs.extend(
        {
            "kind": "data_requirement",
            "ref": f"skill_snapshot/data_requirements.yaml#{item.get('id') or ''}",
            "summary": str(item.get("description") or item.get("id") or "数据需求"),
        }
        for item in required_data
    )
    refs.extend(
        {
            "kind": "output_schema",
            "ref": f"skill_snapshot/output_schemas/{item.get('id') or ''}.json",
            "summary": str(item.get("title") or item.get("id") or "输出 schema"),
        }
        for item in output_items
    )
    return refs


def _node_input_model(
    node_kind: str,
    required_data: list[dict[str, Any]],
    fields: list[Any] | None = None,
) -> dict[str, Any]:
    if node_kind == "form":
        mode = "form"
    elif required_data:
        mode = "manual_upload"
    else:
        mode = "derived"
    return {
        "mode": mode,
        "required_data": required_data,
        "fields": [item for item in fields or [] if isinstance(item, dict)],
    }


def _node_execution_model(node_kind: str, state_machine: list[str], required_data: list[dict[str, Any]]) -> dict[str, Any]:
    if required_data:
        can_run_when = ["required_data_uploaded"]
        degraded_when = ["missing_data"]
    elif node_kind == "form":
        can_run_when = ["form_submitted"]
        degraded_when = []
    else:
        can_run_when = ["dependencies_done"]
        degraded_when = ["dependency_missing"]
    return {
        "state_machine": state_machine,
        "can_run_when": can_run_when,
        "degraded_when": degraded_when,
    }


def _node_tool_model(required_data: list[dict[str, Any]]) -> dict[str, Any]:
    bindings = [
        item.get("tool_binding")
        for item in required_data
        if isinstance(item.get("tool_binding"), dict)
    ]
    return {
        "effective_mode": "manual_upload_only",
        "bindings": bindings,
    }


def _node_business_context(
    index: int,
    node: dict[str, Any],
    strategy_kb_config: dict[str, Any] | None,
) -> dict[str, Any]:
    query = _node_strategy_kb_query(index, node)
    mode = "local-skills.strategy_kb_search"
    if not strategy_kb_config:
        return {
            "status": "missing",
            "query": query,
            "mode": mode,
            "kb_manifest": "",
            "collection_id": "",
            "backend": "",
            "results": [],
            "warnings": ["strategy_kb_not_configured"],
        }
    base = {
        "query": query,
        "mode": mode,
        "kb_manifest": str(strategy_kb_config.get("kb") or ""),
        "collection_id": "",
        "backend": "",
        "results": [],
        "warnings": [],
    }
    try:
        payload = _run_strategy_kb_query(strategy_kb_config, query)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        return {
            **base,
            "status": "error",
            "error": _compact(str(exc), 500),
            "warnings": ["strategy_kb_query_failed"],
        }
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    normalized_results = [_strategy_kb_result(item) for item in results if isinstance(item, dict)]
    normalized_results = [item for item in normalized_results if item.get("passage") or item.get("doc_id")]
    warnings = [str(item) for item in payload.get("warnings", []) if item]
    return {
        **base,
        "status": "available" if normalized_results else "missing",
        "query": str(payload.get("query") or query),
        "backend": str(payload.get("backend") or ""),
        "kb_manifest": str(payload.get("kb_manifest") or strategy_kb_config.get("kb") or ""),
        "collection_id": str(payload.get("collection_id") or ""),
        "results": normalized_results,
        "warnings": warnings,
    }


def _node_strategy_kb_query(index: int, node: dict[str, Any]) -> str:
    name = str(node.get("name") or node.get("id") or "").strip()
    return f"流程{index}:{name}的具体内容" if name else f"流程{index}的具体内容"


def _run_strategy_kb_query(strategy_kb_config: dict[str, Any], query: str) -> dict[str, Any]:
    command = [
        str(strategy_kb_config.get("python") or "python3"),
        str(strategy_kb_config.get("query_script") or ""),
        "--kb",
        str(strategy_kb_config.get("kb") or ""),
        "--query",
        query,
        "--top-k",
        str(int(strategy_kb_config.get("top_k") or 3)),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=20,
    )
    if completed.returncode != 0:
        output = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"strategy_kb_query_failed exit={completed.returncode}: {_compact(output, 500)}")
    payload = json.loads(completed.stdout or "{}")
    if not isinstance(payload, dict):
        raise ValueError("strategy_kb_query returned non-object JSON")
    if payload.get("success") is False:
        raise RuntimeError(str(payload.get("error") or "strategy_kb_query returned success=false"))
    return payload


def _strategy_kb_result(item: dict[str, Any]) -> dict[str, Any]:
    matched_terms = item.get("matched_terms") if isinstance(item.get("matched_terms"), list) else []
    workflow_section = item.get("workflow_section") if isinstance(item.get("workflow_section"), dict) else None
    return {
        "rank": int(item.get("rank") or 0),
        "score": item.get("score", 0),
        "doc_id": str(item.get("doc_id") or ""),
        "doc_title": str(item.get("doc_title") or ""),
        "source_path": str(item.get("source_path") or ""),
        "kb_page_id": str(item.get("kb_page_id") or ""),
        "citation_id": str(item.get("citation_id") or ""),
        "section": str(item.get("section") or ""),
        "passage": _compact(str(item.get("passage") or ""), 1200),
        "matched_terms": [str(value) for value in matched_terms if value],
        "page_type": str(item.get("page_type") or ""),
        **({"workflow_section": _strategy_kb_workflow_section(workflow_section)} if workflow_section else {}),
    }


def _strategy_kb_workflow_section(section: dict[str, Any]) -> dict[str, Any]:
    subsections = section.get("subsections") if isinstance(section.get("subsections"), list) else []
    return {
        "workflow_no": int(section.get("workflow_no") or 0),
        "workflow_title": str(section.get("workflow_title") or ""),
        "heading": str(section.get("heading") or ""),
        "markdown": str(section.get("markdown") or ""),
        "subsections": [
            {
                "title": str(item.get("title") or ""),
                "markdown": str(item.get("markdown") or ""),
            }
            for item in subsections
            if isinstance(item, dict)
        ],
        "source_line_start": int(section.get("source_line_start") or 0),
        "source_line_end": int(section.get("source_line_end") or 0),
    }


def _strategy_ir_business_context(
    index: int,
    node: dict[str, Any],
    skill_snapshot_dir: Path,
    previous_context: dict[str, Any],
) -> dict[str, Any]:
    section = _strategy_ir_workflow_section(index, node, skill_snapshot_dir)
    if not section:
        return previous_context
    query = str(previous_context.get("query") or _node_strategy_kb_query(index, node))
    source_doc = _strategy_ir_source_doc(skill_snapshot_dir)
    result = {
        "rank": 1,
        "score": 1.0,
        "doc_id": "strategy_ir",
        "doc_title": source_doc or "strategy_ir",
        "source_path": str(skill_snapshot_dir / "strategy_ir.yaml"),
        "kb_page_id": "",
        "citation_id": f"strategy-ir-flow-{section.get('workflow_no') or index}",
        "section": "strategy_ir.raw_sections",
        "passage": str(section.get("markdown") or ""),
        "matched_terms": [str(node.get("name") or node.get("id") or "")],
        "page_type": "workflow_section",
        "workflow_section": section,
    }
    warnings = [
        str(value)
        for value in previous_context.get("warnings", [])
        if value and value != "strategy_kb_not_configured"
    ]
    warnings.append("strategy_ir_workflow_section_fallback")
    return {
        **previous_context,
        "status": "available",
        "query": query,
        "mode": "strategy_ir.workflow_section_fallback",
        "backend": "strategy_ir",
        "collection_id": "skill_snapshot",
        "results": [result],
        "warnings": warnings,
    }


def _strategy_ir_source_doc(skill_snapshot_dir: Path) -> str:
    path = skill_snapshot_dir / "strategy_ir.yaml"
    if not path.exists():
        return ""
    match = re.search(r"(?m)^source_doc:\s*(.+)$", path.read_text(encoding="utf-8", errors="ignore"))
    return match.group(1).strip().strip("'\"") if match else ""


def _strategy_ir_workflow_section(index: int, node: dict[str, Any], skill_snapshot_dir: Path) -> dict[str, Any] | None:
    path = skill_snapshot_dir / "strategy_ir.yaml"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8", errors="ignore")
    node_title = str(node.get("name") or node.get("title") or node.get("id") or "")
    pattern = re.compile(r"##\s*流程(?P<no>\d+)[：:]\s*(?P<title>[^\n\\]+)")
    matches = list(pattern.finditer(raw))
    target: re.Match[str] | None = None
    for match in matches:
        if node_title and node_title in match.group("title"):
            target = match
            break
    if not target:
        for match in matches:
            if int(match.group("no") or 0) == index:
                target = match
                break
    if not target:
        return None
    start = target.start()
    next_match = next((item for item in matches if item.start() > start), None)
    end = next_match.start() if next_match else len(raw)
    markdown = _clean_strategy_ir_escaped_markdown(raw[start:end])
    if not markdown.strip():
        return None
    workflow_no = int(target.group("no") or index)
    workflow_title = target.group("title").strip()
    return {
        "workflow_no": workflow_no,
        "workflow_title": workflow_title,
        "heading": f"流程{workflow_no}：{workflow_title}",
        "markdown": markdown,
        "subsections": _markdown_subsections(markdown),
        "source_line_start": raw[:start].count("\n") + 1,
        "source_line_end": raw[:end].count("\n") + 1,
    }


def _clean_strategy_ir_escaped_markdown(value: str) -> str:
    text = re.sub(r"\\\n\s*", "", value)
    text = text.replace("\\n", "\n").replace("\\ ", " ")
    return text.replace('\\"', '"').strip()


def _markdown_subsections(markdown: str) -> list[dict[str, str]]:
    matches = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", markdown))
    subsections: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        subsections.append({"title": match.group(1).strip(), "markdown": markdown[start:end].strip()})
    return subsections


def _node_execution_view(
    index: int,
    node: dict[str, Any],
    business_context: dict[str, Any],
    output_items: list[dict[str, Any]],
) -> dict[str, Any]:
    result = _primary_workflow_section_result(business_context)
    if not result:
        return _missing_node_execution_view(index, node, business_context, output_items)
    workflow = result.get("workflow_section") if isinstance(result.get("workflow_section"), dict) else {}
    subsections = workflow.get("subsections") if isinstance(workflow.get("subsections"), list) else []
    goal_section = _find_subsection(subsections, ("目的",))
    action_section = _find_subsection(subsections, ("执行动作", "数据来源", "分析方法"))
    verification_section = _find_subsection(subsections, ("判断标准", "可执行判断", "落地动作"))
    artifact_section = _find_subsection(subsections, ("表格字段", "产出", "输出", "公式", "规划表"))
    source = {
        "doc_id": str(result.get("doc_id") or ""),
        "doc_title": str(result.get("doc_title") or ""),
        "source_path": str(result.get("source_path") or ""),
        "kb_page_id": str(result.get("kb_page_id") or ""),
        "citation_id": str(result.get("citation_id") or ""),
        "source_line_start": int(workflow.get("source_line_start") or 0),
        "source_line_end": int(workflow.get("source_line_end") or 0),
        "heading": str(workflow.get("heading") or ""),
    }
    action_markdown = str((action_section or {}).get("markdown") or "")
    verification_markdown = str((verification_section or {}).get("markdown") or "")
    artifact_markdown = str((artifact_section or {}).get("markdown") or "")
    artifact_title = _artifact_title(artifact_markdown, output_items)
    fields = _markdown_first_table_rows(action_markdown)
    return {
        "status": "available",
        "workflow_no": int(workflow.get("workflow_no") or index),
        "workflow_title": str(workflow.get("workflow_title") or node.get("name") or node.get("id") or ""),
        "goal": {
            "title": str((goal_section or {}).get("title") or "目的"),
            "markdown": str((goal_section or {}).get("markdown") or ""),
        },
        "action": {
            "title": str((action_section or {}).get("title") or "执行动作"),
            "markdown": action_markdown,
            "steps": _markdown_paragraphs_without_tables(action_markdown),
            "fields": [
                {
                    "id": str(row.get("字段") or row.get("字段名") or row.get("判断项") or row.get("名称") or ""),
                    "label": str(row.get("字段") or row.get("字段名") or row.get("判断项") or row.get("名称") or ""),
                    "description": str(row.get("填写要求") or row.get("填写内容") or row.get("可落地标准") or row.get("说明") or ""),
                    "required": True,
                    "source": "workflow_section_table",
                }
                for row in fields
                if row.get("字段") or row.get("字段名") or row.get("判断项") or row.get("名称")
            ],
        },
        "verification": {
            "title": str((verification_section or {}).get("title") or "验证标准"),
            "markdown": verification_markdown,
            "checks": [
                {
                    "id": str(row.get("判断项") or row.get("字段") or row.get("条件") or row.get("名称") or ""),
                    "standard": str(row.get("可落地标准") or row.get("判断标准") or row.get("填写要求") or row.get("说明") or ""),
                }
                for row in _markdown_first_table_rows(verification_markdown)
                if row.get("判断项") or row.get("字段") or row.get("条件") or row.get("名称")
            ],
        },
        "artifact": {
            "title": artifact_title,
            "markdown": artifact_markdown,
            "outputs": output_items,
        },
        "agent_assist": {
            "mode": "context_only",
            "prompt": f"辅助用户完成节点 `{node.get('name') or node.get('id')}` 的中间产物。",
            "suggested_questions": [
                "这一步需要我填写哪些字段？",
                "我填的内容是否满足判断标准？",
                "请根据已有信息整理中间产物草稿。",
            ],
        },
        "source": source,
    }


def _primary_workflow_section_result(business_context: dict[str, Any]) -> dict[str, Any] | None:
    results = business_context.get("results") if isinstance(business_context.get("results"), list) else []
    for item in results:
        if isinstance(item, dict) and isinstance(item.get("workflow_section"), dict):
            return item
    return None


def _missing_node_execution_view(
    index: int,
    node: dict[str, Any],
    business_context: dict[str, Any],
    output_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "missing",
        "workflow_no": index,
        "workflow_title": str(node.get("name") or node.get("id") or ""),
        "goal": {"title": "目的", "markdown": ""},
        "action": {"title": "执行动作", "markdown": "", "steps": [], "fields": []},
        "verification": {"title": "验证标准", "markdown": "", "checks": []},
        "artifact": {"title": _artifact_title("", output_items), "markdown": "", "outputs": output_items},
        "agent_assist": {
            "mode": "context_only",
            "prompt": f"辅助用户完成节点 `{node.get('name') or node.get('id')}` 的中间产物。",
            "suggested_questions": [],
        },
        "source": {
            "doc_id": "",
            "doc_title": "",
            "source_path": "",
            "kb_page_id": "",
            "citation_id": "",
            "source_line_start": 0,
            "source_line_end": 0,
            "heading": "",
            "warnings": [str(value) for value in business_context.get("warnings", []) if value],
        },
    }


def _find_subsection(subsections: list[Any], keywords: tuple[str, ...]) -> dict[str, Any] | None:
    for item in subsections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        if any(keyword in title for keyword in keywords):
            return item
    return None


def _markdown_first_table_rows(markdown: str) -> list[dict[str, str]]:
    rows = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
        elif rows:
            break
    if len(rows) < 2:
        return []
    header = rows[0]
    data_rows = rows[2:] if all(set(cell.replace(":", "").replace("-", "").strip()) == set() for cell in rows[1]) else rows[1:]
    output: list[dict[str, str]] = []
    for row in data_rows:
        if len(row) != len(header):
            continue
        output.append({header[index]: row[index] for index in range(len(header))})
    return output


def _markdown_paragraphs_without_tables(markdown: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if not stripped:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current).strip())
    return [item for item in paragraphs if item]


def _artifact_title(markdown: str, output_items: list[dict[str, Any]]) -> str:
    match = re.search(r"《[^》]+》", markdown)
    if match:
        return match.group(0)
    if output_items:
        return str(output_items[0].get("title") or output_items[0].get("id") or "节点中间产物")
    return "节点中间产物"


def _node_source_trace(
    requirement_ids: list[str],
    output_items: list[dict[str, Any]],
    business_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace = {
        "workflow_ref": "skill_snapshot/workflow.dag.yaml",
        "data_requirement_refs": [f"skill_snapshot/data_requirements.yaml#{requirement_id}" for requirement_id in requirement_ids],
        "output_schema_refs": [
            f"skill_snapshot/output_schemas/{item.get('id')}.json"
            for item in output_items
            if item.get("id")
        ],
        "tool_binding_refs": [f"skill_snapshot/tool_bindings.yaml#{requirement_id}" for requirement_id in requirement_ids],
        "evidence_ref": "skill_snapshot/evidence_schema.yaml",
    }
    if business_context:
        trace["strategy_kb_ref"] = str(business_context.get("kb_manifest") or "")
        trace["strategy_kb_query"] = str(business_context.get("query") or "")
        trace["strategy_kb_citation_refs"] = [
            str(item.get("citation_id"))
            for item in business_context.get("results", [])
            if isinstance(item, dict) and item.get("citation_id")
        ]
    return trace


def _load_skill_yaml_subset(path: Path) -> dict[str, Any]:
    return load_yaml_subset(path)


def _node_kind(source_type: str) -> str:
    if source_type == "form_collect":
        return "form"
    if source_type == "data_collect":
        return "data"
    if source_type in {"compute", "scoring"}:
        return "compute"
    if source_type in {"business_plan_generation"}:
        return "aggregate"
    return "llm"


def _load_output_schema(skill_snapshot_dir: Path, output_id: str) -> dict[str, Any]:
    path = skill_snapshot_dir / "output_schemas" / f"{output_id}.json"
    if not path.exists():
        payload = _fallback_output_schema(output_id)
        return {
            "id": output_id,
            "status": "available",
            "source": "generated_fallback",
            "schema": payload,
            "summary": _output_schema_summary(output_id, payload, source="generated_fallback"),
        }
    payload = read_json(path)
    return {
        "id": output_id,
        "status": "available",
        "source": "skill_snapshot",
        "schema": payload,
        "summary": _output_schema_summary(output_id, payload, source="skill_snapshot"),
    }


def _fallback_output_schema(output_id: str) -> dict[str, Any]:
    title = output_id.replace("_", " ").title()
    return {
        "type": "object",
        "title": title,
        "description": f"Deterministic fallback schema for `{output_id}` because no matching output_schemas JSON file was present.",
        "properties": {
            "rows": {"type": "array", "items": {"type": "object"}},
            "conclusions": {"type": "array", "items": {"type": "string"}},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["rows", "conclusions", "evidence_ids"],
    }


def _output_schema_summary(output_id: str, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    return {
        "id": output_id,
        "status": "available",
        "source": source,
        "title": str(payload.get("title") or output_id),
        "description": str(payload.get("description") or ""),
        "type": str(payload.get("type") or "object"),
        "property_count": len(properties),
        "properties": sorted(str(key) for key in properties.keys()),
        "required": [str(value) for value in payload.get("required", [])] if isinstance(payload.get("required"), list) else [],
    }


def _compile_evidence_contract(payload: dict[str, Any]) -> dict[str, Any]:
    properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    return {
        "status": "available",
        "type": str(payload.get("type") or "object"),
        "required": [str(value) for value in payload.get("required", [])] if isinstance(payload.get("required"), list) else [],
        "properties": sorted(str(key) for key in properties.keys()),
    }


def _compile_data_requirements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("data_requirements") if isinstance(payload.get("data_requirements"), list) else []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": str(item.get("id") or ""),
                "description": str(item.get("description") or ""),
                "required_fields": [str(value) for value in item.get("required_fields", [])],
                "freshness": str(item.get("freshness") or ""),
                "effective_mode": "manual_upload_only",
                "evidence_required": [str(value) for value in item.get("evidence_required", [])],
                "preferred_sources": [str(value) for value in item.get("preferred_sources", [])],
                "fallback_sources": [str(value) for value in item.get("fallback_sources", [])],
            }
        )
    return result


def _compile_scope_form(task_yaml: dict[str, Any], domain_yaml: dict[str, Any]) -> dict[str, Any]:
    input_schema = domain_yaml.get("input_schema") if isinstance(domain_yaml.get("input_schema"), dict) else {}
    scope_form = input_schema.get("scope_form") if isinstance(input_schema.get("scope_form"), dict) else {}
    task_inputs = task_yaml.get("inputs") if isinstance(task_yaml.get("inputs"), dict) else {}
    fields: list[dict[str, Any]] = []
    for key, value in scope_form.items():
        fields.append({"id": str(key), "type": str(value), "default": task_inputs.get(key, "")})
    return {"fields": fields, "presets": _string_list(task_yaml.get("presets"))}


def _compile_aggregate(task_yaml: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    expected = _string_list(task_yaml.get("expected_outputs"))
    if not expected:
        for node in nodes:
            expected.extend(str(output) for output in node.get("outputs", []))
    return {
        "node_id": "generate_listing_plan",
        "outputs": _dedupe(expected),
        "template_ref": "custom/report_template.md.tmpl",
    }


def _compile_rule_registry(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("rules") if isinstance(payload.get("rules"), list) else []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "rule_id": str(item.get("rule_id") or ""),
                "description": str(item.get("description") or ""),
                "condition": str(item.get("condition") or ""),
                "output_label": str(item.get("output_label") or ""),
                "severity": str(item.get("severity") or "info"),
                "runtime": "shells/report_generator/engine",
            }
        )
    return result


def _compile_tool_bindings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("tool_bindings") if isinstance(payload.get("tool_bindings"), dict) else {}
    result: list[dict[str, Any]] = []
    for requirement_id, binding in raw.items():
        if not isinstance(binding, dict):
            binding = {}
        result.append(
            {
                "data_requirement_id": str(requirement_id),
                "declared_primary_tool": str(binding.get("primary_tool") or ""),
                "declared_fallback_tools": [str(value) for value in binding.get("fallback_tools", [])],
                "effective_mode": "manual_upload_only",
            }
        )
    return result


def _read_skill_id(skill_snapshot_dir: Path) -> str:
    skill_yaml = skill_snapshot_dir / "skill.yaml"
    if not skill_yaml.exists():
        return skill_snapshot_dir.name
    try:
        payload = load_yaml_subset(skill_yaml)
    except Exception:
        return skill_snapshot_dir.name
    return str(payload.get("skill_id") or payload.get("id") or skill_snapshot_dir.name)


def _parse_prd_customizations(prd_text: str) -> list[dict[str, str]]:
    if "customizations" not in prd_text.lower() and "customizations 清单" not in prd_text:
        return []
    
    # Try parsing markdown table format first
    customizations = _parse_customizations_table(prd_text)
    if customizations:
        return customizations
    
    # Fallback to simple label parsing
    location = _line_value_after_label(prd_text, "位置")
    behavior = _line_value_after_label(prd_text, "行为")
    acceptance = _line_value_after_label(prd_text, "验收")
    if not (location and behavior and acceptance):
        return []
    return [{"location": location, "behavior": behavior, "acceptance": acceptance}]


def _parse_customizations_table(prd_text: str) -> list[dict[str, str]]:
    """Parse markdown table with id|position|behavior|acceptance columns."""
    lines = prd_text.splitlines()
    in_customizations = False
    header_found = False
    customizations = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Detect customizations section
        if "customizations 清单" in stripped.lower() or "## customizations" in stripped.lower():
            in_customizations = True
            continue
        
        if not in_customizations:
            continue
        
        # Stop at next section
        if stripped.startswith("##") and "customizations" not in stripped.lower():
            break
        
        # Look for table header with position/behavior/acceptance
        if "|" in stripped and ("position" in stripped.lower() or "behavior" in stripped.lower()):
            header_found = True
            continue
        
        # Skip separator line
        if header_found and stripped.startswith("|") and set(stripped.replace("|", "").replace(" ", "").replace("-", "")) == set():
            continue
        
        # Parse data rows
        if header_found and "|" in stripped and stripped.startswith("|"):
            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) >= 5:  # | id | position | behavior | acceptance |
                cust_id = parts[1].strip("`")
                position = parts[2]
                behavior = parts[3]
                acceptance = parts[4]
                if position and behavior and acceptance:
                    customizations.append({
                        "id": cust_id,
                        "location": position,
                        "behavior": behavior,
                        "acceptance": acceptance,
                    })
    
    return customizations


def _line_value_after_label(text: str, label: str) -> str:
    pattern = re.compile(rf"{re.escape(label)}\s*[:：]\s*(.+)")
    for line in text.splitlines():
        match = pattern.search(line.strip().lstrip("-").strip())
        if match:
            return match.group(1).strip()
    return ""


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
    app_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 2 if app_config else 1,
        "app_slug": app_slug,
        "generated_at": now_iso(),
        "quality_mode": quality_mode,
        **({"app_config_ref": "app.config.json", "shell_kind": app_config.get("shell_kind", "")} if app_config else {}),
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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str) and value:
        return [value]
    return []


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

    if _should_generate_report_generator_shell(run_dir=run_dir, contract=contract):
        return _generate_report_generator_shell_files(
            run_dir=run_dir,
            app_dir=app_dir,
            generated_app_dir=generated_app_dir,
            repo_root=repo_root,
        )
    
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

    # --- generic_spa (archived deterministic fallback) ---
    # 派发优先级：report_generator 固定 Shell（主路径）> image_app > generic_spa。
    # 以下内联模板是最初的 deterministic 骨架，现降级为无 shell_kind 匹配时的通用兜底，
    # 不再作为市场洞察等结构化报告应用的生成路径。
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


def _should_generate_report_generator_shell(*, run_dir: Path, contract: dict[str, Any]) -> bool:
    if str(contract.get("shell_kind") or "") == "report_generator":
        return True
    config_path = Path(run_dir) / "app.config.json"
    if config_path.exists():
        try:
            config = read_json(config_path)
        except Exception:
            return False
        return str(config.get("shell_kind") or "") == "report_generator"
        return False


def _ensure_report_generator_mapping_config(config: dict[str, Any]) -> dict[str, Any]:
    nodes = config.get("nodes") if isinstance(config.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        output_model = node.get("output_model") if isinstance(node.get("output_model"), dict) else {}
        output_items = output_model.get("outputs") if isinstance(output_model.get("outputs"), list) else []
        required_data = []
        input_model = node.get("input_model") if isinstance(node.get("input_model"), dict) else {}
        if isinstance(input_model.get("required_data"), list):
            required_data = [item for item in input_model.get("required_data", []) if isinstance(item, dict)]
        business_context = node.get("business_context") if isinstance(node.get("business_context"), dict) else {}
        node_execution_view = node.get("node_execution_view") if isinstance(node.get("node_execution_view"), dict) else {}
        if not isinstance(node.get("output_field_requirements"), list):
            node["output_field_requirements"] = _node_output_field_requirements(output_items, required_data, node_execution_view)
        if not isinstance(node.get("data_mapping_context"), dict):
            node["data_mapping_context"] = _node_data_mapping_context(
                node,
                required_data,
                output_items,
                node.get("output_field_requirements", []),
                business_context,
                node_execution_view,
            )
    data_capability_index = config.get("data_capability_index")
    if isinstance(data_capability_index, dict) and data_capability_index.get("provider") == "api_doc_index":
        _attach_api_doc_matching_to_nodes(config, data_capability_index)
    return config


def _generate_report_generator_shell_files(
    *,
    run_dir: Path,
    app_dir: Path,
    generated_app_dir: str,
    repo_root: Path,
) -> list[str]:
    shell_root = Path("shells") / "report_generator"
    if not shell_root.exists():
        shell_root = Path(__file__).resolve().parents[2] / "shells" / "report_generator"
    if not shell_root.exists():
        raise ValueError("shells/report_generator is missing")

    if app_dir.exists():
        shutil.rmtree(app_dir)
    ensure_dir(app_dir)
    ensure_dir(app_dir / "public")
    ensure_dir(app_dir / "engine")
    ensure_dir(app_dir / "custom")
    ensure_dir(app_dir / "data")

    shutil.copy2(shell_root / "server" / "server.js", app_dir / "server.js")
    shutil.copy2(shell_root / "server" / "db_archaeologist_worker.mjs", app_dir / "db_archaeologist_worker.mjs")
    shutil.copy2(shell_root / "web" / "index.html", app_dir / "public" / "index.html")
    shutil.copy2(shell_root / "web" / "styles.css", app_dir / "public" / "styles.css")
    shutil.copy2(shell_root / "web" / "app.js", app_dir / "public" / "app.js")
    shutil.copy2(shell_root / "version.txt", app_dir / "shell_version.txt")
    shutil.copy2(shell_root / "contract.schema.json", app_dir / "contract.schema.json")
    for source in sorted((shell_root / "engine").glob("*.py")):
        shutil.copy2(source, app_dir / "engine" / source.name)

    config_path = Path(run_dir) / "app.config.json"
    if not config_path.exists():
        raise ValueError("app.config.json is required for report_generator shell")
    config = read_json(config_path)
    config.setdefault("shell_kind", "report_generator")
    config.setdefault("shell_version", (shell_root / "version.txt").read_text(encoding="utf-8").strip())
    config = _ensure_report_generator_mapping_config(config)
    copied_api_index = False
    data_capability_index = config.get("data_capability_index") if isinstance(config.get("data_capability_index"), dict) else None
    if data_capability_index and data_capability_index.get("provider") == "api_doc_index":
        source_ref = str(data_capability_index.get("source_index_ref") or "data_capability/api_doc_index.json")
        source_path = run_dir / source_ref
        if source_path.exists() and source_path.is_file():
            shutil.copy2(source_path, app_dir / "data" / "api_doc_index.json")
            data_capability_index["runtime_index_ref"] = "data/api_doc_index.json"
            copied_api_index = True
    write_json(app_dir / "app.config.json", config)
    fixture_outputs = _build_report_generator_fixture_outputs(config)
    evidence_pack = _build_report_generator_evidence_pack(config, fixture_outputs)
    ensure_dir(app_dir / "artifacts")
    ensure_dir(app_dir / "evidence")
    write_json(app_dir / "artifacts" / "fixture_outputs.json", fixture_outputs)
    write_json(app_dir / "evidence" / "evidence_pack.json", evidence_pack)
    (app_dir / "final_report.md").write_text(_render_report_generator_final_report(config, fixture_outputs, evidence_pack), encoding="utf-8")
    (app_dir / "runtime_smoke.js").write_text(_report_generator_runtime_smoke_js(), encoding="utf-8")

    readme = f"""# {config.get('app_slug', Path(generated_app_dir).name)}

Generated report_generator shell app.

## Run Locally

```bash
node server.js
```

Open http://127.0.0.1:${{PREVIEW_PORT:-8788}} in your browser.

## Contract

- Shell kind: `{config.get('shell_kind', 'report_generator')}`
- Shell version: `{config.get('shell_version', '')}`
- Config source: `app.config.json`
"""
    (app_dir / "README.md").write_text(readme, encoding="utf-8")

    files_changed = [
        f"{generated_app_dir}/server.js",
        f"{generated_app_dir}/db_archaeologist_worker.mjs",
        f"{generated_app_dir}/README.md",
        f"{generated_app_dir}/app.config.json",
        f"{generated_app_dir}/runtime_smoke.js",
        f"{generated_app_dir}/shell_version.txt",
        f"{generated_app_dir}/contract.schema.json",
        f"{generated_app_dir}/artifacts/fixture_outputs.json",
        f"{generated_app_dir}/evidence/evidence_pack.json",
        f"{generated_app_dir}/final_report.md",
        f"{generated_app_dir}/public/index.html",
        f"{generated_app_dir}/public/styles.css",
        f"{generated_app_dir}/public/app.js",
    ]
    if copied_api_index:
        files_changed.append(f"{generated_app_dir}/data/api_doc_index.json")
    for source in sorted((app_dir / "engine").glob("*.py")):
        files_changed.append(f"{generated_app_dir}/engine/{source.name}")
    return files_changed


def _build_report_generator_fixture_outputs(config: dict[str, Any]) -> dict[str, Any]:
    nodes = [node for node in config.get("nodes", []) if isinstance(node, dict)]
    node_outputs: dict[str, Any] = {}
    flat_outputs: dict[str, Any] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        output_items: dict[str, Any] = {}
        schemas = node.get("output_schema", []) if isinstance(node.get("output_schema"), list) else []
        for schema_item in schemas:
            if not isinstance(schema_item, dict):
                continue
            output_id = str(schema_item.get("id") or "")
            if not output_id:
                continue
            schema = schema_item.get("schema") if isinstance(schema_item.get("schema"), dict) else _fallback_output_schema(output_id)
            value = _fixture_value_for_schema(schema, output_id=output_id, node_id=node_id)
            output_items[output_id] = value
            flat_outputs[output_id] = value
        node_outputs[node_id] = {
            "node_id": node_id,
            "kind": str(node.get("kind") or ""),
            "outputs": output_items,
            "status": "fixture_ready",
        }
    return {
        "schema_version": 1,
        "app_slug": str(config.get("app_slug") or ""),
        "source": "deterministic_report_generator_fixture",
        "node_outputs": node_outputs,
        "outputs": flat_outputs,
    }


def _fixture_value_for_schema(schema: dict[str, Any], *, output_id: str, node_id: str) -> Any:
    schema_type = str(schema.get("type") or "object")
    if schema_type == "object":
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if not properties:
            return {"id": output_id, "source_node_id": node_id, "status": "fixture_ready"}
        payload: dict[str, Any] = {}
        for key, child_schema in properties.items():
            child = child_schema if isinstance(child_schema, dict) else {}
            payload[str(key)] = _fixture_value_for_property(str(key), child, output_id=output_id, node_id=node_id)
        return payload
    return _fixture_value_for_property(output_id, schema, output_id=output_id, node_id=node_id)


def _fixture_value_for_property(key: str, schema: dict[str, Any], *, output_id: str, node_id: str) -> Any:
    schema_type = str(schema.get("type") or "string")
    if schema_type == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        if key == "evidence_ids":
            return [f"ev-{node_id}-{output_id}"]
        if key == "conclusions":
            return [f"Fixture conclusion for {output_id}."]
        return [_fixture_value_for_property("item", item_schema, output_id=output_id, node_id=node_id)]
    if schema_type == "object":
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if properties:
            return {str(child_key): _fixture_value_for_property(str(child_key), child if isinstance(child, dict) else {}, output_id=output_id, node_id=node_id) for child_key, child in properties.items()}
        return {"source_node_id": node_id, "output_id": output_id, "fixture": True}
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    return f"{output_id}_{key}_fixture"


def _build_report_generator_evidence_pack(config: dict[str, Any], fixture_outputs: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    node_outputs = fixture_outputs.get("node_outputs") if isinstance(fixture_outputs.get("node_outputs"), dict) else {}
    for node_id, node_payload in node_outputs.items():
        if not isinstance(node_payload, dict):
            continue
        outputs = node_payload.get("outputs") if isinstance(node_payload.get("outputs"), dict) else {}
        if not outputs:
            items.append(_evidence_item(config, str(node_id), "", f"Node {node_id} is executable in deterministic fixture mode."))
            continue
        for output_id in outputs.keys():
            evidence_id = f"ev-{node_id}-{output_id}"
            items.append(_evidence_item(config, str(node_id), str(output_id), f"Output {output_id} is backed by deterministic fixture evidence.", evidence_id=evidence_id))
    return {
        "schema_version": 1,
        "app_slug": str(config.get("app_slug") or ""),
        "skill_run_id": str(config.get("task_ref", {}).get("task_id") or config.get("app_slug") or "deterministic-run"),
        "evidence_contract": config.get("evidence", {}).get("contract", {}),
        "items": items,
    }


def _evidence_item(config: dict[str, Any], node_id: str, output_id: str, claim: str, *, evidence_id: str | None = None) -> dict[str, Any]:
    skill_run_id = str(config.get("task_ref", {}).get("task_id") or config.get("app_slug") or "deterministic-run")
    return {
        "evidence_id": evidence_id or f"ev-{node_id}",
        "skill_run_id": skill_run_id,
        "step_id": node_id,
        "claim": claim,
        "evidence_type": "deterministic_fixture",
        "source_data": [
            {
                "type": "generated_fixture",
                "path": "artifacts/fixture_outputs.json",
                "output_id": output_id,
            }
        ],
        "computation": {"mode": "deterministic_baseline"},
        "rule_hit": {},
        "confidence": 0.5,
    }


def _render_report_generator_final_report(config: dict[str, Any], fixture_outputs: dict[str, Any], evidence_pack: dict[str, Any]) -> str:
    lines = [
        "# final_report",
        "",
        f"- App slug: `{config.get('app_slug', '')}`",
        f"- Shell kind: `{config.get('shell_kind', '')}`",
        f"- Shell version: `{config.get('shell_version', '')}`",
        "- Source: deterministic CLI baseline fixture outputs",
        "",
        "## Outputs",
    ]
    outputs = fixture_outputs.get("outputs") if isinstance(fixture_outputs.get("outputs"), dict) else {}
    if outputs:
        for output_id, payload in outputs.items():
            evidence_ids = payload.get("evidence_ids") if isinstance(payload, dict) and isinstance(payload.get("evidence_ids"), list) else []
            lines.append(f"- `{output_id}` evidence: {', '.join(str(item) for item in evidence_ids) or 'none'}")
    else:
        lines.append("- none")
    lines.extend(["", "## Evidence"])
    items = evidence_pack.get("items") if isinstance(evidence_pack.get("items"), list) else []
    if items:
        for item in items:
            if isinstance(item, dict):
                lines.append(f"- `{item.get('evidence_id', '')}` node `{item.get('step_id', '')}`: {item.get('claim', '')}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Runtime",
            "- Run `node runtime_smoke.js` to verify health, node execution, and report export.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _report_generator_runtime_smoke_js() -> str:
    return """const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');
const EventEmitter = require('events');
const { spawn } = require('child_process');

const APP_ROOT = __dirname;
const SERVER_JS = path.join(APP_ROOT, 'server.js');
const CONFIG_PATH = path.join(APP_ROOT, 'app.config.json');

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = address && typeof address === 'object' ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function requestJson(port, method, route, payload) {
  return new Promise((resolve, reject) => {
    const body = payload === undefined ? '' : JSON.stringify(payload);
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path: route,
        method,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
        },
      },
      res => {
        let data = '';
        res.setEncoding('utf8');
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => {
          let parsed = {};
          try {
            parsed = data ? JSON.parse(data) : {};
          } catch (error) {
            reject(new Error(`Invalid JSON from ${route}: ${error.message}; body=${data}`));
            return;
          }
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(new Error(`${method} ${route} returned ${res.statusCode}: ${JSON.stringify(parsed)}`));
            return;
          }
          resolve(parsed);
        });
      },
    );
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

async function waitForHealth(port) {
  let lastError = null;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      return await requestJson(port, 'GET', '/api/health');
    } catch (error) {
      lastError = error;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
  throw lastError || new Error('health check timed out');
}

function socketBlocked(error) {
  const message = String(error && error.message ? error.message : error);
  return /EPERM|EACCES|operation not permitted|permission denied|listen/.test(message);
}

function assertNodeViewModel(node) {
  const requiredFields = ['input_model', 'output_model', 'execution_model', 'evidence_model', 'tool_model', 'source_trace', 'business_context', 'node_execution_view'];
  for (const field of requiredFields) {
    if (!node || typeof node[field] !== 'object' || node[field] === null) {
      throw new Error(`Node ${node && node.id ? node.id : '<unknown>'} missing ${field}`);
    }
  }
  if (!['available', 'missing', 'error'].includes(String(node.business_context.status || ''))) {
    throw new Error(`Node ${node.id} has invalid business_context status`);
  }
  if (!['available', 'missing', 'partial'].includes(String(node.node_execution_view.status || ''))) {
    throw new Error(`Node ${node.id} has invalid node_execution_view status`);
  }
  const outputs = node.output_model.outputs;
  if (!Array.isArray(outputs) || outputs.length === 0) {
    throw new Error(`Node ${node.id} missing output_model.outputs`);
  }
  if (!outputs.some(output => output && typeof output.schema === 'object' && output.schema !== null)) {
    throw new Error(`Node ${node.id} missing output_model schema`);
  }
  if (node.kind === 'data') {
    const requiredData = node.input_model.required_data;
    if (!Array.isArray(requiredData) || requiredData.length === 0 || typeof requiredData[0] !== 'object') {
      throw new Error(`Data node ${node.id} missing expanded required_data`);
    }
  }
  if (node.tool_model.effective_mode !== 'manual_upload_only') {
    throw new Error(`Node ${node.id} has invalid tool mode`);
  }
}

function assertOutputFieldRequirements(config) {
  const nodes = Array.isArray(config.nodes) ? config.nodes : [];
  const mappingNodes = nodes.filter(node => Array.isArray(node.output_field_requirements) && node.output_field_requirements.length > 0);
  if (mappingNodes.length === 0) {
    throw new Error('No node exposes output_field_requirements');
  }
  const requiredKeys = ['output_id', 'field_path', 'field_name', 'title', 'description', 'type', 'required', 'source_schema_ref'];
  for (const node of mappingNodes) {
    for (const field of node.output_field_requirements) {
      for (const key of requiredKeys) {
        if (!Object.prototype.hasOwnProperty.call(field, key)) {
          throw new Error(`Node ${node.id} output_field_requirements missing ${key}`);
        }
      }
    }
    if (!node.data_mapping_context || node.data_mapping_context.output_field_count !== node.output_field_requirements.length) {
      throw new Error(`Node ${node.id} missing data_mapping_context field count`);
    }
    if (!node.data_mapping_context.multi_api_mapping || node.data_mapping_context.multi_api_mapping.enabled !== true) {
      throw new Error(`Node ${node.id} missing multi_api_mapping config`);
    }
  }
  const topProducts = nodes.find(node => node.id === 'collect_top_products');
  if (topProducts && Array.isArray(topProducts.output_field_requirements)) {
    const names = topProducts.output_field_requirements.map(field => String(field.field_name || ''));
    const expected = ['排名', '店铺名', '商品链接', '商品主图', '销量/支付买家数', 'GMV/交易指数', '客单价', '价格带', '产品类型', '材质', '功能', '风格', '场景', '主卖点', '主图元素', '是否高增速', '爆款原因'];
    for (const name of expected) {
      if (!names.includes(name)) {
        throw new Error(`collect_top_products missing business output field ${name}: ${names.join(',')}`);
      }
    }
    const imageField = topProducts.output_field_requirements.find(field => field.field_name === '商品主图');
    if (!imageField || !String(imageField.description || '').includes('视觉表达')) {
      throw new Error(`collect_top_products 商品主图 lost business description: ${JSON.stringify(imageField)}`);
    }
  }
}

function assertDataCapabilityIndex(config) {
  const index = config.data_capability_index;
  if (!index) return;
  if (index.provider !== 'api_doc_index') {
    throw new Error(`Unexpected data capability provider: ${JSON.stringify(index)}`);
  }
  if (index.status !== 'available') {
    throw new Error(`Data capability index not available: ${JSON.stringify(index)}`);
  }
  const runtimeRef = String(index.runtime_index_ref || 'data/api_doc_index.json');
  if (runtimeRef.includes('..') || path.isAbsolute(runtimeRef)) {
    throw new Error(`Unsafe api_doc_index runtime ref: ${runtimeRef}`);
  }
  const indexPath = path.join(APP_ROOT, runtimeRef);
  if (!fs.existsSync(indexPath)) {
    throw new Error(`api_doc_index missing: ${indexPath}`);
  }
  const payload = readJson(indexPath);
  if (!Array.isArray(payload.apis)) {
    throw new Error(`api_doc_index missing apis: ${JSON.stringify(payload).slice(0, 300)}`);
  }
}

function assertNodeExecutionView(config) {
  const nodes = Array.isArray(config.nodes) ? config.nodes : [];
  const first = nodes[0];
  if (!first || !first.node_execution_view || first.node_execution_view.status !== 'available') {
    throw new Error('First node missing available node_execution_view');
  }
  const view = first.node_execution_view;
  const fields = Array.isArray(view.action && view.action.fields) ? view.action.fields.map(field => String(field.id || field.label || '')) : [];
  for (const required of ['分析类目', '分析产品线', '店铺阶段', '当前目标']) {
    if (!fields.includes(required)) {
      throw new Error(`First node execution view missing field ${required}`);
    }
  }
  const checks = Array.isArray(view.verification && view.verification.checks) ? view.verification.checks.map(check => String(check.id || '')) : [];
  if (!checks.includes('类目是否清楚')) {
    throw new Error('First node execution view missing verification checks');
  }
  if (!String(view.artifact && view.artifact.title || '').includes('市场洞察项目定义表')) {
    throw new Error('First node execution view missing artifact title');
  }
}

function assertConfigViewModel(config) {
  const nodes = Array.isArray(config.nodes) ? config.nodes : [];
  if (nodes.length === 0) throw new Error('No nodes declared in app.config.json');
  nodes.forEach(assertNodeViewModel);
  if (!nodes.some(node => node.kind === 'data' && Array.isArray(node.input_model.required_data) && node.input_model.required_data.length > 0)) {
    throw new Error('No data node exposes expanded required_data');
  }
  if (!nodes.some(node => Array.isArray(node.output_model.outputs) && node.output_model.outputs.some(output => output && typeof output.schema === 'object'))) {
    throw new Error('No node exposes output_model.outputs[].schema');
  }
  assertOutputFieldRequirements(config);
  assertDataCapabilityIndex(config);
  if (nodes.some(node => node.business_context && node.business_context.status === 'available')) {
    assertNodeExecutionView(config);
  }
}

function buildSmokeArtifact(node) {
  const view = node && node.node_execution_view ? node.node_execution_view : {};
  const action = view.action || {};
  const fields = Array.isArray(action.fields) ? action.fields : [];
  const rows = fields.length > 0
    ? fields.map(field => ({
        field_id: String(field.id || field.label || ''),
        label: String(field.label || field.id || ''),
        requirement: String(field.description || ''),
        value: `smoke:${String(field.label || field.id || '')}`,
        required: field.required !== false,
        status: 'filled',
        source: 'runtime_smoke',
      }))
    : [{ field_id: 'smoke', label: 'smoke', requirement: 'runtime smoke input', value: 'ok', required: false, status: 'filled', source: 'runtime_smoke' }];
  return {
    title: String(view.artifact && view.artifact.title || node.name || node.id || 'runtime smoke artifact'),
    node_id: node.id,
    node_name: node.name || node.id,
    status: 'ready',
    rows,
    missing_required: [],
    generated_at: new Date().toISOString(),
    source: 'runtime_smoke',
  };
}

function firstDependentNode(nodes, upstreamNodeId) {
  return nodes.find(node => Array.isArray(node.depends_on) && node.depends_on.includes(upstreamNodeId));
}

function firstDataMappingNode(nodes) {
  return nodes.find(node => Array.isArray(node.output_field_requirements) && node.output_field_requirements.length > 0 && (
    node.kind === 'data'
    || (Array.isArray(node.data_requirements) && node.data_requirements.length > 0)
    || (node.input_model && Array.isArray(node.input_model.required_data) && node.input_model.required_data.length > 0)
  ));
}

function assertUpstreamPropagation(payload, upstreamNodeId) {
  const result = payload && payload.result ? payload.result : payload;
  const upstream = result && Array.isArray(result.upstream_artifacts) ? result.upstream_artifacts : [];
  if (!upstream.some(item => item && item.source_node_id === upstreamNodeId)) {
    throw new Error(`Downstream node did not receive upstream_artifacts from ${upstreamNodeId}: ${JSON.stringify(payload)}`);
  }
}

function assertDbAgentStatus(status) {
  if (!status || typeof status !== 'object') {
    throw new Error(`DB agent status is not an object: ${JSON.stringify(status)}`);
  }
  if (!['ok', 'degraded'].includes(String(status.status || ''))) {
    throw new Error(`DB agent status must be ok or degraded: ${JSON.stringify(status)}`);
  }
  if (!Array.isArray(status.allowed_tools) || !status.allowed_tools.includes('select_tools_for_task')) {
    throw new Error(`DB agent status missing allowed tool list: ${JSON.stringify(status)}`);
  }
  if (status.status === 'degraded' && !status.reason) {
    throw new Error(`DB agent degraded status must include reason: ${JSON.stringify(status)}`);
  }
}

function assertPiAgentStatus(status) {
  if (!status || typeof status !== 'object') {
    throw new Error(`PI agent status is not an object: ${JSON.stringify(status)}`);
  }
  if (status.provider !== 'pi_agent') {
    throw new Error(`PI agent status missing provider: ${JSON.stringify(status)}`);
  }
  if (!['ready', 'not_configured', 'error'].includes(String(status.status || ''))) {
    throw new Error(`PI agent status invalid: ${JSON.stringify(status)}`);
  }
  if (!Array.isArray(status.capabilities) || !status.capabilities.includes('data_mapping_advice')) {
    throw new Error(`PI agent status missing data_mapping_advice capability: ${JSON.stringify(status)}`);
  }
}

function assertPiAgentAdvice(result) {
  if (!result || typeof result !== 'object') {
    throw new Error(`PI agent advice result is not an object: ${JSON.stringify(result)}`);
  }
  if (result.provider !== 'pi_agent') {
    throw new Error(`PI agent advice missing provider: ${JSON.stringify(result)}`);
  }
  const advice = result.advice;
  if (!advice || advice.schema_version !== 'pi-data-mapping-advice-v1') {
    throw new Error(`PI agent advice missing schema: ${JSON.stringify(result)}`);
  }
  if (advice.requires_human_confirmation !== true) {
    throw new Error(`PI agent advice must require human confirmation: ${JSON.stringify(advice)}`);
  }
  if (result.data_mapping_contract && result.data_mapping_contract.status === 'confirmed') {
    throw new Error(`PI agent advice must not confirm data mapping contract: ${JSON.stringify(result)}`);
  }
  if (!result.evidence_ref || !String(result.evidence_ref).includes('pi_mapping_advice.json')) {
    throw new Error(`PI agent advice missing evidence ref: ${JSON.stringify(result)}`);
  }
}

function ensureFakeDbAgentSpecPack() {
  const root = path.join(APP_ROOT, 'artifacts', 'fake_db_archaeologist_spec_pack');
  const scriptsDir = path.join(root, 'scripts');
  const toolsDir = path.join(root, 'src', 'tools');
  fs.mkdirSync(scriptsDir, { recursive: true });
  fs.mkdirSync(toolsDir, { recursive: true });
  fs.writeFileSync(path.join(scriptsDir, 'ts_loader.mjs'), '');
  fs.writeFileSync(path.join(toolsDir, 'select_tools_for_task.mjs'), `
export function selectToolsForTask(args) {
  return {
    task: args.task,
    intent: '类目 | 商品',
    recommended_tools: [{
      tool_id: 'auto_商品域_商品分析',
      call_order: 1,
      reason: 'runtime smoke fixture',
      required_params: ['category', 'period'],
      missing_params: [],
      source_apis: ['agent_goods_category_top_products'],
      quality_score: 0.91,
      risks: []
    }],
    blocked_or_deprioritized: [],
    next_question: '已就绪，可直接调用。'
  };
}
`);
  fs.writeFileSync(path.join(toolsDir, 'get_api_asset_card.mjs'), `
export function getApiAssetCard(args) {
  return {
    found: true,
    card: {
      api_id: args.api_id,
      name: 'Runtime Smoke 商品排行 API',
      method: 'POST',
      path: args.api_id,
      domain: '商品域',
      capability: '商品分析',
      request_schema: { query: [{ name: 'category', type: 'string', required: true, desc: '类目' }] },
      response_schema: {
        root: 'data.rows[]',
        fields: [
          { path: 'data.rows.rank', name: 'rank', type: 'number', desc: '排名' },
          { path: 'data.rows.price', name: 'price', type: 'number', desc: '价格' }
        ]
      }
    },
    lineage_text: 'runtime_smoke asset_card'
  };
}
`);
  return root;
}

function assertDbAgentToolPlan(result) {
  if (!result || result.ok !== true) {
    throw new Error(`DB agent tool plan failed: ${JSON.stringify(result)}`);
  }
  if (!result.known_params || result.known_params.category !== '入户地垫' || result.known_params.period !== '近30天') {
    throw new Error(`DB agent did not extract upstream known_params: ${JSON.stringify(result.known_params)}`);
  }
  const tools = result.payload && Array.isArray(result.payload.recommended_tools) ? result.payload.recommended_tools : [];
  const localProvider = result.provider === 'api_doc_index' || result.db_agent_status && result.db_agent_status.provider === 'api_doc_index';
  if (localProvider) {
    if (!result.payload.strategy_results || !result.payload.strategy_results.field_coverage_rerank) {
      throw new Error(`DB agent local provider missing strategy_results: ${JSON.stringify(result.payload)}`);
    }
    if (!Array.isArray(result.payload.selected_api_ids) || result.payload.selected_api_ids.length === 0) {
      throw new Error(`DB agent local provider missing selected_api_ids: ${JSON.stringify(result.payload)}`);
    }
  } else if (!tools.some(tool => tool.tool_id === 'auto_商品域_商品分析')) {
    throw new Error(`DB agent tool plan missing expected tool: ${JSON.stringify(result.payload)}`);
  }
  const contract = result.data_mapping_contract;
  if (!contract || contract.schema_version !== 'data-mapping-contract-v2') {
    throw new Error(`DB agent result missing data_mapping_contract: ${JSON.stringify(result)}`);
  }
  if (contract.status !== 'suggested') {
    throw new Error(`DB agent contract should be suggested after tool_plan: ${JSON.stringify(contract)}`);
  }
  if (!contract.known_params || contract.known_params.category !== '入户地垫' || contract.known_params.period !== '近30天') {
    throw new Error(`DB agent contract missing known_params: ${JSON.stringify(contract)}`);
  }
  const candidateApis = Array.isArray(contract.candidate_apis) ? contract.candidate_apis : [];
  if (candidateApis.length === 0) {
    throw new Error(`DB agent contract missing candidate API: ${JSON.stringify(contract)}`);
  }
}

function smokeApiIdFromToolPlan(result) {
  const selected = Array.isArray(result && result.payload && result.payload.selected_api_ids) ? result.payload.selected_api_ids : [];
  if (selected[0]) return selected[0];
  const tools = Array.isArray(result && result.payload && result.payload.recommended_tools) ? result.payload.recommended_tools : [];
  for (const tool of tools) {
    const apis = Array.isArray(tool.source_apis) ? tool.source_apis : [];
    if (apis[0]) return apis[0];
  }
  return 'agent_goods_category_top_products';
}

function assertDbAgentAssetCard(result) {
  if (!result || result.ok !== true) {
    throw new Error(`DB agent asset_card failed: ${JSON.stringify(result)}`);
  }
  if (result.action !== 'asset_card') {
    throw new Error(`DB agent asset_card returned wrong action: ${JSON.stringify(result)}`);
  }
  const fields = result.payload && Array.isArray(result.payload.api_response_fields) ? result.payload.api_response_fields : [];
  if (fields.length === 0 || !fields.some(field => field.path || field.name)) {
    throw new Error(`DB agent asset_card missing API response fields: ${JSON.stringify(result.payload)}`);
  }
  const outputFields = result.payload && Array.isArray(result.payload.output_field_requirements) ? result.payload.output_field_requirements : [];
  if (outputFields.length === 0) {
    throw new Error(`DB agent asset_card missing output_field_requirements: ${JSON.stringify(result.payload)}`);
  }
  if (!result.data_mapping_contract || result.data_mapping_contract.schema_version !== 'data-mapping-contract-v2') {
    throw new Error(`DB agent asset_card missing contract: ${JSON.stringify(result)}`);
  }
  if (!Array.isArray(result.data_mapping_contract.selected_apis)) {
    throw new Error(`DB agent asset_card missing selected_apis: ${JSON.stringify(result.data_mapping_contract)}`);
  }
}

function assertDbAgentMultiApiMapping(result) {
  if (!result || result.ok !== true) {
    throw new Error(`DB agent multi API mapping failed: ${JSON.stringify(result)}`);
  }
  if (result.action !== 'suggest_multi_api_mapping') {
    throw new Error(`DB agent multi API mapping returned wrong action: ${JSON.stringify(result)}`);
  }
  const contract = result.data_mapping_contract;
  if (!contract || contract.schema_version !== 'data-mapping-contract-v2') {
    throw new Error(`DB agent multi API mapping missing v2 contract: ${JSON.stringify(result)}`);
  }
  if (!Array.isArray(contract.field_coverage_plan) || contract.field_coverage_plan.length === 0) {
    throw new Error(`DB agent multi API mapping missing field_coverage_plan: ${JSON.stringify(contract)}`);
  }
  if (!contract.coverage_summary || typeof contract.coverage_summary.total !== 'number') {
    throw new Error(`DB agent multi API mapping missing coverage_summary: ${JSON.stringify(contract)}`);
  }
  if (!contract.join_plan || contract.join_plan.grain !== 'unknown') {
    throw new Error(`DB agent multi API mapping missing join_plan: ${JSON.stringify(contract)}`);
  }
  if (contract.node_id === 'collect_top_products') {
    const names = contract.field_coverage_plan.map(field => String(field.field_name || ''));
    if (!names.includes('商品主图') || !names.includes('爆款原因')) {
      throw new Error(`DB agent multi API mapping lost business field names: ${JSON.stringify(names)}`);
    }
    const derivedNames = new Set((Array.isArray(contract.derived_field_plan) ? contract.derived_field_plan : []).map(field => String(field.field_name || '')));
    for (const name of ['功能', '风格', '主图元素', '爆款原因']) {
      if (!derivedNames.has(name)) {
        throw new Error(`DB agent multi API mapping missing derived field ${name}: ${JSON.stringify([...derivedNames])}`);
      }
    }
  }
}

async function runHttpSmoke(config) {
  const port = await findFreePort();
  const hasApiDocIndex = Boolean(config.data_capability_index);
  const fakeSpecPack = hasApiDocIndex ? '' : ensureFakeDbAgentSpecPack();
  const childEnv = { ...process.env, APP_ROOT, PREVIEW_PORT: String(port), PORT: String(port), PI_BIN: path.join(APP_ROOT, 'missing-pi-runtime-smoke') };
  if (!hasApiDocIndex) childEnv.DB_ARCHAEOLOGIST_SPEC_PACK = fakeSpecPack;
  const child = spawn(process.execPath, [SERVER_JS], {
    cwd: APP_ROOT,
    env: childEnv,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', chunk => { stdout += chunk.toString(); });
  child.stderr.on('data', chunk => { stderr += chunk.toString(); });
  try {
    const serverExited = new Promise((resolve, reject) => {
      child.once('exit', code => {
        reject(new Error(`server exited before health check: code=${code}; stderr=${stderr}; stdout=${stdout}`));
      });
    });
    const health = await Promise.race([waitForHealth(port), serverExited]);
    if (!health.config_loaded || health.shell_kind !== 'report_generator') {
      throw new Error(`Unexpected health payload: ${JSON.stringify(health)}`);
    }
    const remoteConfig = await requestJson(port, 'GET', '/api/config');
    if (remoteConfig.schema_version !== 'app-config-v1') {
      throw new Error(`Unexpected schema_version: ${remoteConfig.schema_version}`);
    }
    assertConfigViewModel(remoteConfig);
    const dbAgentStatus = await requestJson(port, 'GET', '/api/db-agent/status');
    assertDbAgentStatus(dbAgentStatus);
    const piAgentStatus = await requestJson(port, 'GET', '/api/pi-agent/status');
    assertPiAgentStatus(piAgentStatus);
    const nodes = Array.isArray(config.nodes) ? config.nodes : [];
    if (nodes.length === 0) throw new Error('No nodes declared in app.config.json');
    const firstNode = nodes[0];
    const nodeDetail = await requestJson(port, 'GET', `/api/nodes/${firstNode.id}`);
    assertNodeViewModel(nodeDetail);
    const smokeArtifact = buildSmokeArtifact(firstNode);
    const nodeResult = await requestJson(port, 'POST', `/api/nodes/${firstNode.id}/run`, {
      inputs: { smoke: true, source: 'runtime_smoke' },
      artifact: firstNode.kind === 'form' ? smokeArtifact : undefined,
    });
    if (nodeResult.status !== 'done') {
      throw new Error(`Node smoke failed: ${JSON.stringify(nodeResult)}`);
    }
    if (firstNode.kind === 'form' && firstNode.node_execution_view && firstNode.node_execution_view.status === 'available') {
      const artifactPath = path.join(APP_ROOT, 'artifacts', `${firstNode.id}.json`);
      if (!fs.existsSync(artifactPath)) {
        throw new Error(`Form node artifact missing: ${artifactPath}`);
      }
    }
    const dependentNode = firstDependentNode(nodes, firstNode.id);
    if (dependentNode) {
      const dependentResult = await requestJson(port, 'POST', `/api/nodes/${dependentNode.id}/run`, {
        inputs: { smoke: true, source: 'runtime_smoke_downstream' },
        upstream_artifacts: [{
          source_node_id: firstNode.id,
          source_node_name: firstNode.name || firstNode.id,
          ...smokeArtifact,
        }],
      });
      if (dependentResult.status !== 'done') {
        throw new Error(`Dependent node smoke failed: ${JSON.stringify(dependentResult)}`);
      }
      assertUpstreamPropagation(dependentResult, firstNode.id);
      if (firstDataMappingNode([dependentNode])) {
        const toolPlan = await requestJson(port, 'POST', '/api/db-agent/query', {
          node_id: dependentNode.id,
          action: 'tool_plan',
          upstream_artifacts: [{
            source_node_id: firstNode.id,
            source_node_name: firstNode.name || firstNode.id,
            artifact: {
              title: '《市场洞察项目定义表》',
              rows: [
                { label: '分析类目', value: '入户地垫' },
                { label: '分析周期', value: '近30天' },
                { label: '分析产品线', value: '地垫' },
              ],
            },
          }],
        });
        assertDbAgentToolPlan(toolPlan);
      }
    }
    const dataMappingNode = firstDataMappingNode(nodes);
    if (dataMappingNode) {
      const smokeToolPlan = await requestJson(port, 'POST', '/api/db-agent/query', {
        node_id: dataMappingNode.id,
        action: 'tool_plan',
        known_params: { category: '入户地垫', period: '近30天' },
      });
      assertDbAgentToolPlan(smokeToolPlan);
      const smokeApiId = smokeApiIdFromToolPlan(smokeToolPlan);
      const assetCard = await requestJson(port, 'POST', '/api/db-agent/query', {
        node_id: dataMappingNode.id,
        action: 'asset_card',
        api_id: smokeApiId,
      });
      assertDbAgentAssetCard(assetCard);
      const multiApiMapping = await requestJson(port, 'POST', '/api/db-agent/query', {
        node_id: dataMappingNode.id,
        action: 'suggest_multi_api_mapping',
        selected_apis: assetCard.data_mapping_contract.selected_apis,
        selected_api_asset_cards: [assetCard.payload.selected_api_asset_card],
      });
      assertDbAgentMultiApiMapping(multiApiMapping);
      const piAdvice = await requestJson(port, 'POST', '/api/pi-agent/query', {
        node_id: dataMappingNode.id,
        message: 'runtime smoke PI fallback',
        data_mapping_contract: multiApiMapping.data_mapping_contract,
        selected_api_asset_cards: [assetCard.payload.selected_api_asset_card],
        field_coverage_plan: multiApiMapping.data_mapping_contract.field_coverage_plan,
        join_plan: multiApiMapping.data_mapping_contract.join_plan,
      });
      assertPiAgentAdvice(piAdvice);
    }
    const report = await requestJson(port, 'POST', '/api/export/final_report', {
      narrative: 'Deterministic smoke report.',
      rule_outputs: [],
    });
    if (!report.report_markdown || !fs.existsSync(path.join(APP_ROOT, 'final_report.md'))) {
      throw new Error(`Report export failed: ${JSON.stringify(report)}`);
    }
  } finally {
    if (!child.killed) child.kill('SIGTERM');
    await new Promise(resolve => {
      if (child.exitCode !== null) {
        resolve();
      } else {
        child.once('exit', resolve);
      }
    });
    if (process.env.RUNTIME_SMOKE_DEBUG === '1') {
      console.log(stdout);
      console.error(stderr);
    }
  }
}

function directRequest(handleApi, method, route, payload) {
  return new Promise((resolve, reject) => {
    const body = payload === undefined ? '' : JSON.stringify(payload);
    const req = new EventEmitter();
    req.method = method;
    const chunks = [];
    const res = {
      statusCode: 200,
      headers: {},
      setHeader(name, value) {
        this.headers[String(name).toLowerCase()] = value;
      },
      writeHead(status, headers) {
        this.statusCode = status;
        this.headers = { ...this.headers, ...(headers || {}) };
      },
      write(chunk) {
        if (chunk !== undefined) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
      },
      end(chunk) {
        if (chunk !== undefined) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
        const raw = Buffer.concat(chunks).toString('utf8');
        let parsed = {};
        try {
          parsed = raw ? JSON.parse(raw) : {};
        } catch (error) {
          reject(new Error(`Invalid direct JSON from ${route}: ${error.message}; body=${raw}`));
          return;
        }
        if (this.statusCode < 200 || this.statusCode >= 300) {
          reject(new Error(`${method} ${route} returned ${this.statusCode}: ${JSON.stringify(parsed)}`));
          return;
        }
        resolve(parsed);
      },
    };
    handleApi(req, res, route).catch(reject);
    process.nextTick(() => {
      if (body) req.emit('data', body);
      req.emit('end');
    });
  });
}

async function runDirectSmoke(config) {
  process.env.APP_ROOT = APP_ROOT;
  process.env.PI_BIN = path.join(APP_ROOT, 'missing-pi-runtime-smoke');
  const hasApiDocIndex = Boolean(config.data_capability_index);
  if (hasApiDocIndex) {
    delete process.env.DB_ARCHAEOLOGIST_SPEC_PACK;
  }
  const serverModule = require(SERVER_JS);
  if (typeof serverModule.handleApi !== 'function') {
    throw new Error('server.js does not export handleApi for direct smoke');
  }
  const health = await directRequest(serverModule.handleApi, 'GET', '/api/health');
  if (!health.config_loaded || health.shell_kind !== 'report_generator') {
    throw new Error(`Unexpected direct health payload: ${JSON.stringify(health)}`);
  }
  const remoteConfig = await directRequest(serverModule.handleApi, 'GET', '/api/config');
  if (remoteConfig.schema_version !== 'app-config-v1') {
    throw new Error(`Unexpected direct schema_version: ${remoteConfig.schema_version}`);
  }
  assertConfigViewModel(remoteConfig);
  const dbAgentStatus = await directRequest(serverModule.handleApi, 'GET', '/api/db-agent/status');
  assertDbAgentStatus(dbAgentStatus);
  const piAgentStatus = await directRequest(serverModule.handleApi, 'GET', '/api/pi-agent/status');
  assertPiAgentStatus(piAgentStatus);
  const nodes = Array.isArray(config.nodes) ? config.nodes : [];
  if (nodes.length === 0) throw new Error('No nodes declared in app.config.json');
  const firstNode = nodes[0];
  const nodeDetail = await directRequest(serverModule.handleApi, 'GET', `/api/nodes/${firstNode.id}`);
  assertNodeViewModel(nodeDetail);
  const smokeArtifact = buildSmokeArtifact(firstNode);
  const nodeResult = await directRequest(serverModule.handleApi, 'POST', `/api/nodes/${firstNode.id}/run`, {
    inputs: { smoke: true, source: 'runtime_smoke_direct' },
    artifact: firstNode.kind === 'form' ? smokeArtifact : undefined,
  });
  if (nodeResult.status !== 'done') {
    throw new Error(`Direct node smoke failed: ${JSON.stringify(nodeResult)}`);
  }
  if (firstNode.kind === 'form' && firstNode.node_execution_view && firstNode.node_execution_view.status === 'available') {
    const artifactPath = path.join(APP_ROOT, 'artifacts', `${firstNode.id}.json`);
    if (!fs.existsSync(artifactPath)) {
      throw new Error(`Direct form node artifact missing: ${artifactPath}`);
    }
  }
  const dependentNode = firstDependentNode(nodes, firstNode.id);
  if (dependentNode) {
    const dependentResult = await directRequest(serverModule.handleApi, 'POST', `/api/nodes/${dependentNode.id}/run`, {
      inputs: { smoke: true, source: 'runtime_smoke_downstream_direct' },
      upstream_artifacts: [{
        source_node_id: firstNode.id,
        source_node_name: firstNode.name || firstNode.id,
        ...smokeArtifact,
      }],
    });
    if (dependentResult.status !== 'done') {
      throw new Error(`Direct dependent node smoke failed: ${JSON.stringify(dependentResult)}`);
    }
    assertUpstreamPropagation(dependentResult, firstNode.id);
    if (firstDataMappingNode([dependentNode])) {
      if (!hasApiDocIndex) {
        const fakeSpecPack = ensureFakeDbAgentSpecPack();
        process.env.DB_ARCHAEOLOGIST_SPEC_PACK = fakeSpecPack;
      }
      const toolPlan = await directRequest(serverModule.handleApi, 'POST', '/api/db-agent/query', {
        node_id: dependentNode.id,
        action: 'tool_plan',
        upstream_artifacts: [{
          source_node_id: firstNode.id,
          source_node_name: firstNode.name || firstNode.id,
          artifact: {
            title: '《市场洞察项目定义表》',
            rows: [
              { label: '分析类目', value: '入户地垫' },
              { label: '分析周期', value: '近30天' },
              { label: '分析产品线', value: '地垫' },
            ],
          },
        }],
      });
      assertDbAgentToolPlan(toolPlan);
    }
  }
  const dataMappingNode = firstDataMappingNode(nodes);
  if (dataMappingNode) {
    if (!hasApiDocIndex) {
      const fakeSpecPack = ensureFakeDbAgentSpecPack();
      process.env.DB_ARCHAEOLOGIST_SPEC_PACK = fakeSpecPack;
    }
    const smokeToolPlan = await directRequest(serverModule.handleApi, 'POST', '/api/db-agent/query', {
      node_id: dataMappingNode.id,
      action: 'tool_plan',
      known_params: { category: '入户地垫', period: '近30天' },
    });
    assertDbAgentToolPlan(smokeToolPlan);
    const smokeApiId = smokeApiIdFromToolPlan(smokeToolPlan);
    const assetCard = await directRequest(serverModule.handleApi, 'POST', '/api/db-agent/query', {
      node_id: dataMappingNode.id,
      action: 'asset_card',
      api_id: smokeApiId,
    });
    assertDbAgentAssetCard(assetCard);
    const multiApiMapping = await directRequest(serverModule.handleApi, 'POST', '/api/db-agent/query', {
      node_id: dataMappingNode.id,
      action: 'suggest_multi_api_mapping',
      selected_apis: assetCard.data_mapping_contract.selected_apis,
      selected_api_asset_cards: [assetCard.payload.selected_api_asset_card],
    });
    assertDbAgentMultiApiMapping(multiApiMapping);
    const piAdvice = await directRequest(serverModule.handleApi, 'POST', '/api/pi-agent/query', {
      node_id: dataMappingNode.id,
      message: 'runtime smoke PI fallback direct',
      data_mapping_contract: multiApiMapping.data_mapping_contract,
      selected_api_asset_cards: [assetCard.payload.selected_api_asset_card],
      field_coverage_plan: multiApiMapping.data_mapping_contract.field_coverage_plan,
      join_plan: multiApiMapping.data_mapping_contract.join_plan,
    });
    assertPiAgentAdvice(piAdvice);
  }
  const report = await directRequest(serverModule.handleApi, 'POST', '/api/export/final_report', {
    narrative: 'Deterministic smoke report.',
    rule_outputs: [],
  });
  if (!report.report_markdown || !fs.existsSync(path.join(APP_ROOT, 'final_report.md'))) {
    throw new Error(`Direct report export failed: ${JSON.stringify(report)}`);
  }
}

async function main() {
  if (!fs.existsSync(SERVER_JS)) throw new Error('server.js missing');
  if (!fs.existsSync(CONFIG_PATH)) throw new Error('app.config.json missing');
  const config = readJson(CONFIG_PATH);
  try {
    await runHttpSmoke(config);
    console.log('runtime_smoke_ok');
  } catch (error) {
    if (!socketBlocked(error)) throw error;
    await runDirectSmoke(config);
    console.log('runtime_smoke_ok_direct');
  }
}

main().catch(error => {
  console.error(`runtime_smoke_failed: ${error.message}`);
  process.exit(1);
});
"""


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

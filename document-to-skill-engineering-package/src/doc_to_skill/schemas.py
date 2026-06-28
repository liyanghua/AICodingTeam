from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class StepType(str, Enum):
    FORM_COLLECT = "form_collect"
    DATA_COLLECT = "data_collect"
    BROWSER_COLLECT = "browser_collect"
    EXTERNAL_RESEARCH = "external_research"
    LLM_STRUCTURING = "llm_structuring"
    COMPUTE = "compute"
    SCORING = "scoring"
    BUSINESS_PLAN_GENERATION = "business_plan_generation"
    MULTI_SOURCE_ANALYSIS = "multi_source_analysis"
    COMPUTE_AND_LLM_EXTRACT = "compute_and_llm_extract"


class BusinessQuestion(BaseModel):
    id: str
    question: str
    required_outputs: list[str] = Field(default_factory=list)


class OutputSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    schema_ref: str | None = None


class WorkflowStep(BaseModel):
    step_id: str
    title: str
    step_type: StepType | str
    purpose: str = ""
    depends_on: list[str] = Field(default_factory=list)
    data_requirement_ids: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)


class DataRequirement(BaseModel):
    id: str
    description: str
    required_fields: list[str] = Field(default_factory=list)
    freshness: str = "30d"
    preferred_sources: list[str] = Field(default_factory=list)
    fallback_sources: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=lambda: [
        "source_name", "query_params", "fetched_at", "raw_response_id"
    ])


class RuleSpec(BaseModel):
    rule_id: str
    description: str
    condition: str = ""
    output_label: str = ""
    severity: str = "info"


class StrategyIR(BaseModel):
    strategy_id: str
    name: str
    version: str = "0.1.0"
    source_doc: str
    business_scenes: list[str] = Field(default_factory=list)
    business_questions: list[BusinessQuestion] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    workflow_steps: list[WorkflowStep] = Field(default_factory=list)
    data_requirements: list[DataRequirement] = Field(default_factory=list)
    rules: list[RuleSpec] = Field(default_factory=list)
    raw_sections: dict[str, str] = Field(default_factory=dict)


class ToolContract(BaseModel):
    tool_id: str
    name: str
    type: str
    domain: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    business_semantics: dict[str, Any] = Field(default_factory=dict)
    quality_checks: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=list)
    governance: dict[str, Any] = Field(default_factory=dict)
    fallback_tools: list[str] = Field(default_factory=list)


class EvidencePack(BaseModel):
    evidence_id: str
    skill_run_id: str
    step_id: str
    claim: str
    evidence_type: str
    source_data: list[dict[str, Any]] = Field(default_factory=list)
    computation: dict[str, Any] = Field(default_factory=dict)
    rule_hit: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.BusinessView = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  const STAGE_GROUPS = [
    {
      id: "requirement",
      agents: ["orchestrator", "requirements"],
      artifactPaths: [
        "task.yaml",
        "context.md",
        "requirements/brief_analysis.json",
        "requirements/requirement_quality_report.json",
        "acceptance_criteria.md",
        "context_pack.md",
      ],
    },
    {
      id: "design",
      agents: ["product", "architect", "ux", "qa"],
      artifactPaths: ["prd.md", "tech_spec.md", "ui_spec.md", "eval.md", "planning/acceptance_coverage_matrix.md", "planning/planning_quality_report.json"],
    },
    {
      id: "implementation",
      agents: ["coder"],
      artifactPaths: [
        "coding_prompt.md",
        "codex/implementation_trace.json",
        "codex/slice_loop_state.json",
        "implementation_completion_gate.md",
        "implementation_completion_gate.json",
        "codex/diff.patch",
      ],
    },
    { id: "quality", agents: ["reviewer", "verifier"], artifactPaths: ["review_report.md", "test_report.md"] },
    { id: "delivery", agents: ["publisher"], artifactPaths: ["final_report.md"] },
  ];

  function toBusinessViewModel(run, i18n) {
    const status = overallStatus(run);
    const stages = STAGE_GROUPS.map((group) => buildStage(run, i18n, group));
    return {
      runId: run.run_id || "",
      brief: run.brief || "",
      status,
      statusLabel: statusLabel(i18n, status),
      headline: headline(run, i18n, status),
      stages,
      health: buildHealth(run, i18n),
      artifactQuality: buildArtifactQuality(run, i18n),
      memoryRecall: buildMemoryRecall(run, i18n),
      requirementUnderstanding: buildRequirementUnderstanding(run, i18n),
      acceptanceCoverage: buildAcceptanceCoverage(run, i18n),
      sliceLoop: buildSliceLoop(run, i18n),
      completionGate: buildCompletionGate(run, i18n),
      releaseReadiness: buildReleaseReadiness(run, i18n),
      githubPr: buildGithubPr(run, i18n),
      stagingReadiness: buildStagingReadiness(run, i18n),
      qualityGates: buildGates(run, i18n),
      deliverables: buildArtifacts(run, i18n),
      recommendedArtifact: recommendedArtifact(run, i18n),
      implementationFlow: run.implementation_trace || {},
      acceptance: run.acceptance || { status: "not_started", steps: [], applied: false },
      applyGate: run.apply_gate || {},
      nextActions: run.next_actions || [],
      risks: buildRisks(run, i18n),
      engineering: {
        runId: run.run_id || "",
        status: run.status || "",
        executor: run.executor || "",
        failureCategory: run.failure_category || "",
        logs: run.logs || [],
        events: run.events || [],
        diffSummary: run.diff_summary || {},
        healthSummary: run.health_summary || {},
        qualityReport: run.quality_report || {},
      },
    };
  }

  function buildHealth(run, i18n) {
    const health = run.health_summary || {};
    return {
      status: health.status || "unknown",
      label: health.label || lookup(i18n, "health.unknownLabel", unknown(i18n)),
      summary: health.summary || lookup(i18n, "health.unknownSummary", ""),
      warnings: health.warnings || [],
      warningGroups: health.warning_groups || health.warningGroups || [],
      blockers: health.blockers || [],
    };
  }

  function buildArtifactQuality(run, i18n) {
    const quality = run.quality_report || {};
    return {
      status: quality.status || "unknown",
      score: quality.score == null ? null : quality.score,
      summary: quality.summary || lookup(i18n, "quality.unknownSummary", ""),
      checks: quality.checks || [],
    };
  }

  function buildMemoryRecall(run, i18n) {
    const recall = run.memory_recall || {};
    const matches = Array.isArray(recall.matches) ? recall.matches : [];
    const recommendedSkills = Array.isArray(recall.recommended_skills) ? recall.recommended_skills : [];
    const strategy = recall.context_strategy || {};
    return {
      summary: matches.length
        ? lookup(i18n, "memoryRecall.summaryWithMatches", "").replace("{count}", String(matches.length))
        : lookup(i18n, "memoryRecall.empty", ""),
      matches,
      recommendedSkills,
      contextStrategy: {
        reuse: strategy.reuse || [],
        avoid: strategy.avoid || [],
        checklist: strategy.checklist || [],
      },
    };
  }

  function buildRequirementUnderstanding(run, i18n) {
    const payload = run.requirement_understanding || {};
    const analysis = payload.brief_analysis || {};
    const quality = payload.quality_report || {};
    const blockers = Array.isArray(quality.blockers) ? quality.blockers : [];
    const warnings = Array.isArray(quality.warnings) ? quality.warnings : [];
    const skills = Array.isArray(analysis.recommended_skills) ? analysis.recommended_skills : [];
    const status = quality.status || (Object.keys(analysis).length ? "unknown" : "not_generated");
    return {
      status,
      statusLabel: lookup(i18n, `complexTask.status.${status}`, status),
      summary: quality.summary || lookup(i18n, "complexTask.requirementEmpty", ""),
      complexity: analysis.complexity || "",
      planningMode: analysis.planning_mode || "",
      llmDraftRequested: Boolean(analysis.llm_draft_requested),
      blockingQuestions: analysis.blocking_questions || [],
      assumptions: analysis.assumptions || [],
      recommendedSkills: skills,
      blockers,
      warnings,
      draftArtifacts: payload.draft_artifacts || {},
    };
  }

  function buildAcceptanceCoverage(run, i18n) {
    const coverage = run.acceptance_coverage || {};
    const criteria = Array.isArray(coverage.acceptance_criteria) ? coverage.acceptance_criteria : [];
    const slices = Array.isArray(coverage.slices) ? coverage.slices : [];
    const covered = criteria.filter((item) => (item.covering_slice_ids || []).length);
    const orphanCriteria = criteria.filter((item) => !(item.covering_slice_ids || []).length);
    const orphanSlices = slices.filter((item) => !(item.acceptance_criteria_ids || []).length);
    return {
      summary: criteria.length
        ? lookup(i18n, "complexTask.coverageSummary", "")
            .replace("{covered}", String(covered.length))
            .replace("{total}", String(criteria.length))
            .replace("{slices}", String(slices.length))
        : lookup(i18n, "complexTask.coverageEmpty", ""),
      criteria,
      slices,
      coveredCount: covered.length,
      totalCriteria: criteria.length,
      sliceCount: slices.length,
      orphanCriteria,
      orphanSlices,
      ready: Boolean(criteria.length) && !orphanCriteria.length && !orphanSlices.length,
    };
  }

  function buildSliceLoop(run, i18n) {
    const loop = run.slice_loop || {};
    const status = loop.status || (loop.enabled ? "unknown" : "not_generated");
    return {
      status,
      statusLabel: lookup(i18n, `complexTask.status.${status}`, status),
      summary: loop.enabled
        ? lookup(i18n, "complexTask.sliceLoopSummary", "")
            .replace("{completed}", String((loop.completed_slice_ids || []).length))
            .replace("{pending}", String((loop.pending_slice_ids || []).length))
        : lookup(i18n, "complexTask.sliceLoopEmpty", ""),
      executionStrategy: loop.execution_strategy || "",
      currentSliceId: loop.current_slice_id || "",
      completedSliceIds: loop.completed_slice_ids || [],
      pendingSliceIds: loop.pending_slice_ids || [],
      slices: loop.slices || [],
      blockers: loop.blockers || [],
      riskEvents: loop.risk_events || [],
      nextAction: loop.next_action || "",
    };
  }

  function buildCompletionGate(run, i18n) {
    const gate = run.implementation_completion_gate || {};
    const status = gate.status || "not_generated";
    return {
      status,
      statusLabel: lookup(i18n, `complexTask.status.${status}`, status),
      summary: gate.summary || lookup(i18n, "complexTask.completionEmpty", ""),
      checks: Array.isArray(gate.checks) ? gate.checks : [],
      evidence: gate.evidence || {},
      blockers: gate.blockers || [],
      nextAction: gate.next_action || "",
    };
  }

  function buildReleaseReadiness(run, i18n) {
    const readiness = run.release_readiness || {};
    const gates = Array.isArray(readiness.gates) ? readiness.gates : [];
    const prDraft = readiness.pr_draft || {};
    const decision = readiness.release_decision || "not_generated";
    return {
      decision,
      decisionLabel: lookup(i18n, `releaseReadiness.decisions.${decision}`, decision),
      summary: readiness.summary || lookup(i18n, "releaseReadiness.empty", ""),
      gates,
      prDraft,
      blockers: readiness.blockers || [],
      warnings: readiness.warnings || [],
      nextActions: readiness.next_actions || [],
      generatedAt: readiness.generated_at || "",
    };
  }

  function buildGithubPr(run, i18n) {
    const githubPr = run.github_pr || {};
    const ciStatus = run.ci_status || {};
    const pr = githubPr.pr || {};
    const prStatus = githubPr.status || "not_started";
    const ciState = ciStatus.status || "not_started";
    return {
      status: prStatus,
      statusLabel: lookup(i18n, `githubPr.status.${prStatus}`, prStatus),
      pr,
      ciStatus: ciState,
      ciStatusLabel: lookup(i18n, `githubPr.ciStatus.${ciState}`, ciState),
      checks: ciStatus.checks || [],
      summary: ciStatus.summary || githubPr.next_action || lookup(i18n, "githubPr.noPr", ""),
      warnings: [...(githubPr.warnings || []), ...(ciStatus.warnings || [])],
      blockers: [...(githubPr.blockers || []), ...(ciStatus.blockers || [])],
      nextAction: ciStatus.next_action || githubPr.next_action || "",
    };
  }

  function buildStagingReadiness(run, i18n) {
    const readiness = run.staging_readiness || {};
    const decision = readiness.staging_decision || "not_generated";
    return {
      decision,
      decisionLabel: lookup(i18n, `stagingReadiness.decisions.${decision}`, decision),
      summary: readiness.summary || lookup(i18n, "stagingReadiness.empty", ""),
      gates: Array.isArray(readiness.gates) ? readiness.gates : [],
      blockers: readiness.blockers || [],
      warnings: readiness.warnings || [],
      nextActions: readiness.next_actions || [],
      evidence: readiness.evidence || {},
      generatedAt: readiness.generated_at || "",
    };
  }

  function buildStage(run, i18n, group) {
    const status = stageStatus(run, group);
    const copy = lookup(i18n, `stages.${group.id}`, {});
    const stageArtifacts = (run.artifacts || [])
      .filter((artifact) => group.artifactPaths.includes(artifact.path) || group.artifactPaths.includes(artifact.label))
      .map((artifact) => {
        const artifactText = artifactCopy(i18n, artifact);
        return {
          ...artifact,
          title: artifactText.title || artifact.label || artifact.path || unknown(i18n),
          description: artifactText.description || "",
        };
      });
    return {
      id: group.id,
      title: copy.title || unknown(i18n),
      description: copy.description || "",
      status,
      statusLabel: statusLabel(i18n, status),
      tone: lookup(i18n, `status.${status}.tone`, "muted"),
      summary: lookup(copy, `summary.${status}`, copy.description || ""),
      rows: [
        { label: lookup(i18n, "stages.rowLabels.done", "done"), text: copy.done || "" },
        { label: lookup(i18n, "stages.rowLabels.attention", "attention"), text: attentionText(run, i18n, status, copy.attention || "") },
        { label: lookup(i18n, "stages.rowLabels.next", "next"), text: copy.next || "" },
      ],
      actions: stageActions(status, stageArtifacts, run),
      artifacts: stageArtifacts,
      agentIds: group.agents,
    };
  }

  function stageStatus(run, group) {
    if ((run.failure_category || "") === "permission_error" && group.id === "implementation") {
      return "needs_attention";
    }
    const agentMap = new Map((run.stages || []).map((stage) => [stage.id, stage]));
    const rawAgents = group.agents.map((id) => agentMap.get(id)).filter(Boolean);
    const agents = group.id === "requirement" ? rawAgents.filter((agent) => agent.status !== "not_run") : rawAgents;
    if (group.id === "delivery") {
      const deliveryStatus = acceptanceDeliveryStatus(run);
      if (deliveryStatus) {
        return deliveryStatus;
      }
    }
    if (agents.some((agent) => isFailed(agent.status))) {
      return "needs_attention";
    }
    if (agents.some((agent) => isRunning(agent.status))) {
      return "processing";
    }
    if (group.id === "requirement" && agents.length && agents.every((agent) => agent.status === "completed")) {
      return "completed";
    }
    if (agents.length === group.agents.length && agents.every((agent) => agent.status === "completed")) {
      return "completed";
    }
    if (run.status === "failed" && group.id === "quality") {
      return "needs_attention";
    }
    return "not_started";
  }

  function overallStatus(run) {
    if ((run.failure_category || "") === "permission_error") {
      return "needs_attention";
    }
    if (run.status === "failed") {
      return "needs_attention";
    }
    const acceptedStatus = acceptanceStatus(run);
    if (acceptedStatus === "completed") {
      return "completed";
    }
    if (acceptedStatus === "failed") {
      return "needs_attention";
    }
    if (acceptedStatus === "queued" || acceptedStatus === "running") {
      return "processing";
    }
    if (run.status === "completed" && (run.apply_gate || {}).status === "passed") {
      return "waiting_confirmation";
    }
    if (run.status === "completed") {
      return "completed";
    }
    if (run.status === "running" || run.status === "starting" || run.status === "pending") {
      return "processing";
    }
    return "not_started";
  }

  function acceptanceDeliveryStatus(run) {
    const status = acceptanceStatus(run);
    if (status === "completed") return "completed";
    if (status === "failed") return "needs_attention";
    if (status === "queued" || status === "running") return "processing";
    if (run.status === "completed" && (run.apply_gate || {}).status === "passed") {
      return "waiting_confirmation";
    }
    return "";
  }

  function acceptanceStatus(run) {
    return ((run.acceptance || {}).status || "not_started");
  }

  function buildGates(run, i18n) {
    return (run.gates || []).map((gate) => {
      const gateCopy = lookup(i18n, `gates.${gate.id}`, {});
      const gateStatus = gate.status === "passed" ? "completed" : gate.status === "planned" ? "planned" : gate.status === "blocked" ? "needs_attention" : normalizeStatus(gate.status);
      return {
        id: gate.id,
        title: gateCopy.title || gate.label || gate.id || unknown(i18n),
        status: gateStatus,
        statusLabel: statusLabel(i18n, gateStatus),
        tone: lookup(i18n, `status.${gateStatus}.tone`, "muted"),
        detail: gateCopy[gate.status] || gate.reason || missingText(gate, i18n) || lookup(i18n, `status.${gateStatus}.description`, ""),
      };
    });
  }

  function buildArtifacts(run, i18n) {
    return (run.artifacts || []).map((artifact) => {
      const copy = artifactCopy(i18n, artifact);
      return {
        ...artifact,
        title: copy.title || artifact.label || artifact.path || unknown(i18n),
        description: copy.description || "",
      };
    });
  }

  function recommendedArtifact(run, i18n) {
    const artifacts = buildArtifacts(run, i18n).filter((artifact) => artifact.exists);
    const priority = ["staging_readiness.md", "github_pr.md", "ci_status.md", "pr_draft.md", "release_readiness.md", "final_report.md", "review_report.md", "test_report.md", "codex/diff.patch", "prd.md"];
    for (const path of priority) {
      const found = artifacts.find((artifact) => artifact.path === path);
      if (found) return found;
    }
    return artifacts[0] || null;
  }

  function artifactCopy(i18n, artifact) {
    const artifacts = lookup(i18n, "artifacts", {});
    for (const key of [artifact.path, artifact.label]) {
      if (key && artifacts && Object.prototype.hasOwnProperty.call(artifacts, key)) {
        return artifacts[key];
      }
    }
    return {};
  }

  function buildRisks(run, i18n) {
    const risks = run.risk_events || [];
    if (!risks.length) {
      return [lookup(i18n, "actions.noRisk", "no risk")];
    }
    return risks.map((risk) => lookup(i18n, `actions.${risk}`, risk));
  }

  function stageActions(status, artifacts, run) {
    const actions = [];
    if (artifacts.some((artifact) => artifact.exists)) {
      actions.push("viewDeliverables");
    }
    if (status === "needs_attention" || (run.risk_events || []).length) {
      actions.push("viewRisks");
    }
    actions.push("viewEngineering");
    return actions;
  }

  function headline(run, i18n, status) {
    if ((run.failure_category || "") === "permission_error") {
      return lookup(i18n, "actions.permission_error", "permission error");
    }
    if (status === "waiting_confirmation") {
      return lookup(i18n, "actions.readyForConfirmation", "");
    }
    return lookup(i18n, `status.${status}.description`, "");
  }

  function attentionText(run, i18n, status, fallback) {
    if (status !== "needs_attention") {
      return fallback;
    }
    if ((run.failure_category || "") === "permission_error") {
      return lookup(i18n, "actions.permission_error", fallback);
    }
    return lookup(i18n, "actions.defaultAttention", fallback);
  }

  function statusLabel(i18n, status) {
    return lookup(i18n, `status.${status}.label`, status || unknown(i18n));
  }

  function normalizeStatus(status) {
    if (status === "completed" || status === "passed") return "completed";
    if (status === "running" || status === "starting" || status === "pending") return "processing";
    if (status === "failed" || status === "blocked") return "needs_attention";
    if (status === "planned") return "planned";
    return "not_started";
  }

  function isFailed(status) {
    return status === "failed" || status === "blocked";
  }

  function isRunning(status) {
    return status === "running" || status === "starting" || status === "pending";
  }

  function missingText(gate, i18n) {
    if (gate.missing_artifacts && gate.missing_artifacts.length) {
      const prefix = lookup(i18n, "actions.missingArtifactsPrefix", "missing");
      return `${prefix}: ${gate.missing_artifacts.join(", ")}`;
    }
    return "";
  }

  function lookup(source, path, fallback) {
    if (!source) return fallback;
    const parts = String(path).split(".");
    let value = source;
    for (const part of parts) {
      if (value && Object.prototype.hasOwnProperty.call(value, part)) {
        value = value[part];
      } else {
        return fallback;
      }
    }
    return value == null ? fallback : value;
  }

  function unknown(i18n) {
    return lookup(i18n, "app.unknown", "未知项");
  }

  return { toBusinessViewModel, lookup, STAGE_GROUPS };
});

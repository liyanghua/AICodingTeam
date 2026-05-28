(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.BusinessView = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  const STAGE_GROUPS = [
    { id: "requirement", agents: ["orchestrator"], artifactPaths: ["task.yaml", "context.md"] },
    { id: "design", agents: ["product", "architect", "ux", "qa"], artifactPaths: ["prd.md", "tech_spec.md", "ui_spec.md", "eval.md"] },
    { id: "implementation", agents: ["coder"], artifactPaths: ["coding_prompt.md", "codex/implementation_trace.json", "codex/diff.patch"] },
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
    const agents = group.agents.map((id) => agentMap.get(id)).filter(Boolean);
    if (group.id === "delivery" && run.status === "completed" && (run.apply_gate || {}).status === "passed") {
      return "waiting_confirmation";
    }
    if (agents.some((agent) => isFailed(agent.status))) {
      return "needs_attention";
    }
    if (agents.some((agent) => isRunning(agent.status))) {
      return "processing";
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
    const priority = ["final_report.md", "review_report.md", "test_report.md", "codex/diff.patch", "prd.md"];
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

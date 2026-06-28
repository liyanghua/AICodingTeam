import assert from "node:assert/strict";
import test from "node:test";

import {
  applyLayerIteration,
  buildImagePrompt,
  buildPlanningCards,
  buildVisualBaseline,
  diagnoseInput,
  generateCreativeSchemes,
} from "../src/shared/dingdang-core.js";

const sampleInput = {
  productName: "云感商务办公椅",
  productDescription: "米色皮质办公椅，高靠背，弧形木纹扶手，五爪底座和静音滚轮",
  platform: "天猫",
  category: "办公椅",
  priceBand: "高客单价",
  sellingPoints: "人体工学支撑、荔枝纹 PU 皮、静音滚轮、原木扶手",
  audience: "重视居家办公品质的城市白领",
  targetMode: "8张首图测点击率",
  referenceKind: "详情页参考",
};

test("diagnoseInput locks platform strategy and reference/task type", () => {
  const diagnosis = diagnoseInput(sampleInput);

  assert.equal(diagnosis.referenceType, "详情页参考-风格借鉴");
  assert.equal(diagnosis.taskType, "8张首图测点击率");
  assert.equal(diagnosis.platformStrategy.platform, "天猫");
  assert.match(diagnosis.platformStrategy.tone, /克制高级/);
  assert.ok(diagnosis.platformStrategy.negativeWords.includes("促销"));
});

test("generateCreativeSchemes returns three single-select schemes with eight image rows each", () => {
  const diagnosis = diagnoseInput(sampleInput);
  const schemes = generateCreativeSchemes(sampleInput, diagnosis);

  assert.equal(schemes.length, 3);
  assert.deepEqual(
    schemes.map((scheme) => scheme.id),
    ["A", "B", "C"],
  );
  for (const scheme of schemes) {
    assert.equal(scheme.rows.length, 8);
    assert.ok(scheme.controlVariables.some((item) => item.includes("产品角度")));
    assert.ok(scheme.riskTips.length > 0);
  }
  assert.notEqual(schemes[0].hookStrategy, schemes[1].hookStrategy);
});

test("buildVisualBaseline and buildPlanningCards preserve the PRD consistency model", () => {
  const diagnosis = diagnoseInput(sampleInput);
  const scheme = generateCreativeSchemes(sampleInput, diagnosis)[0];
  const baseline = buildVisualBaseline(sampleInput, diagnosis, scheme);
  const cards = buildPlanningCards(sampleInput, diagnosis, scheme, baseline);

  assert.equal(baseline.colorSystem.main, "暖米白 70%");
  assert.equal(baseline.lightSystem.temperature, "4500K");
  assert.equal(cards.length, 8);
  assert.equal(cards[0].consistency.light, baseline.lightSystem.temperature);
  assert.equal(cards[7].layerType, "白底层");
});

test("buildImagePrompt emits the fixed three-layer Stage 4 structure and bounded negative words", () => {
  const diagnosis = diagnoseInput(sampleInput);
  const scheme = generateCreativeSchemes(sampleInput, diagnosis)[0];
  const baseline = buildVisualBaseline(sampleInput, diagnosis, scheme);
  const card = buildPlanningCards(sampleInput, diagnosis, scheme, baseline)[0];
  const prompt = buildImagePrompt(sampleInput, diagnosis, scheme, baseline, card, 1);

  assert.match(prompt, /【视觉基因声明】/);
  assert.match(prompt, /【第一层:视觉锚定层】/);
  assert.match(prompt, /【冲突解决协议】/);
  assert.match(prompt, /【第二层:氛围调整层】/);
  assert.match(prompt, /【第三层:信息叠加层】/);
  assert.match(prompt, /【负面词清单】/);
  assert.ok((prompt.match(/禁止/g) ?? []).length >= 3);

  const negativeLine = prompt
    .split("\n")
    .find((line) => line.startsWith("【负面词清单】"));
  assert.ok(negativeLine);
  assert.ok(negativeLine.replace("【负面词清单】", "").split("、").filter(Boolean).length <= 10);
});

test("applyLayerIteration appends targeted instructions without rewriting other layers", () => {
  const updated = applyLayerIteration("原始 Prompt", {
    imageIndex: 5,
    layer: "第二层:氛围调整层",
    instruction: "背景换成木地板，滚轮更突出",
  });

  assert.match(updated, /第 5 张/);
  assert.match(updated, /第二层:氛围调整层/);
  assert.match(updated, /背景换成木地板/);
  assert.match(updated, /^原始 Prompt/);
});

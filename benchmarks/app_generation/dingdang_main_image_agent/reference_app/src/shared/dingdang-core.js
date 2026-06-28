export const platformStrategies = {
  天猫: {
    platform: "天猫",
    tone: "克制高级，强调品质、材质和场景氛围",
    firstImageStyle: "场景氛围 + 材质细节 + 克制高级",
    forbidden: "避免促销标签、价格刺激和高饱和色块",
    negativeWords: ["促销", "价格", "霓虹", "强对比", "杂乱", "夸张", "低俗"],
  },
  淘宝: {
    platform: "淘宝",
    tone: "直接清晰，强调卖点标签和使用结果",
    firstImageStyle: "卖点标签 + 使用结果 + 信息清晰",
    forbidden: "避免堆叠过多标签和遮挡产品主体",
    negativeWords: ["杂乱", "低俗", "侵权", "像素", "过曝", "变形"],
  },
  抖音: {
    platform: "抖音",
    tone: "强视觉冲击，短文案，单点爆破",
    firstImageStyle: "强视觉 + 短文案 + 单点爆破",
    forbidden: "避免信息密度过高和长句解释",
    negativeWords: ["杂乱", "长文案", "低俗", "侵权", "像素", "变形"],
  },
  拼多多: {
    platform: "拼多多",
    tone: "促销感、性价比和耐用证据",
    firstImageStyle: "促销感 + 性价比 + 耐用证据",
    forbidden: "避免卖点含糊和价值感不足",
    negativeWords: ["低俗", "侵权", "像素", "变形", "过曝", "虚假承诺"],
  },
};

const defaultStrategy = platformStrategies.淘宝;

export function diagnoseInput(input) {
  const platformStrategy = platformStrategies[input.platform] ?? defaultStrategy;
  return {
    referenceType: inferReferenceType(input.referenceKind),
    taskType: inferTaskType(input.targetMode),
    platformStrategy,
    requiredFields: [
      "产品图",
      "平台",
      "类目",
      "价格带",
      "核心卖点",
      "目标人群",
    ],
    blockers: [
      "Stage 1 必须确认任务类型",
      "Stage 2 必须单选方案，禁止混搭",
    ],
  };
}

export function generateCreativeSchemes(input, diagnosis) {
  const product = productKind(input.category);
  const sellingPoints = splitSellingPoints(input.sellingPoints);
  const sharedControls = [
    "产品角度保持正面微侧 15 度",
    "主色调、色温、光源方向保持一致",
    "产品结构、材质纹理、关键部件位置不变",
  ];

  return [
    {
      id: "A",
      name: product === "beauty" ? "成分信任型" : "轻奢场景型",
      coreHypothesis: `用户第一眼关心${product === "beauty" ? "成分可信和质地高级感" : "产品放进真实空间后的品质感"}`,
      hookStrategy: "场景代入",
      platformFit: diagnosis.platformStrategy.tone,
      variableDescription: "仅变化使用场景和局部卖点表达",
      changedVariables: ["场景背景", "单张主卖点"],
      controlVariables: sharedControls,
      riskTips: ["若目标用户只关注价格，场景型方案的点击钩子可能偏弱"],
      rows: buildRows("scene", input, sellingPoints),
    },
    {
      id: "B",
      name: "卖点冲击型",
      coreHypothesis: "用户第一眼关心核心利益是否清晰、是否值得点开",
      hookStrategy: "痛点利益",
      platformFit: diagnosis.platformStrategy.firstImageStyle,
      variableDescription: "仅变化单点利益钩子和证据呈现方式",
      changedVariables: ["首屏钩子", "证据表达"],
      controlVariables: sharedControls,
      riskTips: ["若平台偏克制，强标签需要降低饱和度和面积"],
      rows: buildRows("benefit", input, sellingPoints),
    },
    {
      id: "C",
      name: product === "beauty" ? "质地细节型" : "材质信任型",
      coreHypothesis: "用户第一眼关心材质、细节和购买风险是否可控",
      hookStrategy: "细节信任",
      platformFit: "适合高客单价、视觉敏感或需要消除顾虑的商品",
      variableDescription: "仅变化细节证据和信任层级",
      changedVariables: ["材质细节", "信任证据"],
      controlVariables: sharedControls,
      riskTips: ["细节型图片需要产品图清晰，否则容易被生成模型改形"],
      rows: buildRows("trust", input, sellingPoints),
    },
  ];
}

export function buildVisualBaseline(input, diagnosis, scheme) {
  const product = productKind(input.category);
  const isPremium = input.platform === "天猫" || /高|客单|品质/.test(input.priceBand ?? "");

  const palette =
    product === "beauty"
      ? {
          main: "纯白 75%",
          secondary: "银灰 15%",
          accent: "浅蓝 5%",
          forbidden: "荧光色、大红大紫、廉价渐变",
          temperature: "5000K",
        }
      : {
          main: isPremium ? "暖米白 70%" : "浅灰白 65%",
          secondary: isPremium ? "原木 25%" : "品牌辅助色 25%",
          accent: isPremium ? "深咖 5%" : "深灰 10%",
          forbidden: "高饱和霓虹、硬促销红、杂乱背景",
          temperature: "4500K",
        };

  return {
    schemeId: scheme.id,
    colorSystem: {
      main: palette.main,
      secondary: palette.secondary,
      accent: palette.accent,
      forbidden: palette.forbidden,
    },
    lightSystem: {
      direction: "左侧 45 度",
      temperature: palette.temperature,
      shadow: "柔和过渡，避免硬边和脏灰阴影",
      surface: "自然柔光，保留真实材质纹理，避免过曝",
    },
    fontSystem: {
      title: "思源黑体 Medium",
      body: "思源黑体 Light",
      ratio: "标题:正文 = 3:2",
      align: input.platform === "抖音" ? "居中或左上强钩子" : "左对齐",
    },
    compositionSystem: {
      productRatio: "30%~50%",
      safeArea: "顶部 15% 标题，底部 20% 信息",
      angle: "正面微侧 15 度",
    },
    negativeWords: limitNegativeWords(diagnosis.platformStrategy.negativeWords),
  };
}

export function buildPlanningCards(input, diagnosis, scheme, baseline) {
  return scheme.rows.map((row) => ({
    index: row.index,
    name: row.visualStrategy,
    testGoal: row.hookType,
    layerType: row.index === 8 ? "白底层" : layerTypeForRow(row.index),
    visualSpec: {
      composition: row.index === 8 ? "中心构图，产品占画面 45%" : "三分法，产品位于视觉重心",
      background: row.index === 8 ? "干净白底，保留统一光影" : row.visualStrategy,
      props: row.index === 8 ? "无道具" : "2~4 个低饱和克制道具",
      depth: row.index <= 2 ? "浅景深，背景轻微虚化" : "主体清晰，细节可辨",
    },
    copySpec: {
      main: row.mainCopy,
      sub: row.subCopy,
      titlePosition: input.platform === "抖音" ? "顶部居中安全区" : "顶部左侧安全区",
      avoid: avoidAreas(input),
    },
    consistency: {
      light: baseline.lightSystem.temperature,
      palette: baseline.colorSystem.main,
      angle: baseline.compositionSystem.angle,
      noMixing: "仅允许使用当前方案的 8 张规划，不混搭其他方案",
    },
    testVariable: row.testVariable,
    controlVariable: row.controlVariable,
  }));
}

export function buildImagePrompt(input, diagnosis, scheme, baseline, card, imageIndex = card.index) {
  const productSubject = input.productDescription?.trim() || `${input.productName || "商品"}，${input.category || "电商商品"}`;
  const mustKeep = keyParts(input);
  const negativeWords = limitNegativeWords([
    ...baseline.negativeWords,
    ...diagnosis.platformStrategy.negativeWords,
  ]);

  return [
    `【视觉基因声明】本图属于 8 图套装中的第 ${imageIndex} 张，严格遵循套装视觉基因: 色温 ${baseline.lightSystem.temperature}；主色调 ${baseline.colorSystem.main}、${baseline.colorSystem.secondary}、${baseline.colorSystem.accent}；光照方向 ${baseline.lightSystem.direction}；产品角度 ${baseline.compositionSystem.angle}。`,
    "",
    `【第一层:视觉锚定层】基于用户产品图精确复刻。产品主体:${productSubject}。整体轮廓保持原始比例、宽窄、厚薄和关键曲线。关键细节:${mustKeep.join("、")} 纹理清晰。材质表现遵循产品图真实质感，自然柔光不过曝。严禁偏离: 禁止改变产品结构比例；禁止移动 ${mustKeep[0]} 位置；禁止调整 ${mustKeep[1]} 方向；禁止新增不存在的核心部件。`,
    "",
    "【冲突解决协议】若文字描述与产品图冲突，严格以产品图为准。文字描述结构与产品图不一致时遵循产品图；文字颜色与产品图存在色差时以产品图为准；文字尺寸与产品图比例冲突时以产品图比例为准。",
    "",
    `【第二层:氛围调整层】场景:${card.visualSpec.background}。光照:${baseline.lightSystem.direction} 自然光，色温 ${baseline.lightSystem.temperature}。构图:${card.visualSpec.composition}，产品占画面 ${baseline.compositionSystem.productRatio}。道具:${card.visualSpec.props}。景深:${card.visualSpec.depth}。氛围:${scheme.name}，${diagnosis.platformStrategy.tone}。紧箍咒: 所有场景、光影和道具只能服务背景，不得改变第一层已锁定的产品结构和边缘轮廓。`,
    "",
    `【第三层:信息叠加层】主标题(${card.copySpec.titlePosition}):"${card.copySpec.main}"，${baseline.fontSystem.title}，使用 ${baseline.colorSystem.accent}。副标题(主标题下方):"${card.copySpec.sub}"，${baseline.fontSystem.body}，浅灰色。避让区: 严禁遮挡 ${card.copySpec.avoid.join("、")}。禁止添加额外价格、促销角标、强饱和贴纸。`,
    "",
    `【负面词清单】${negativeWords.join("、")}`,
  ].join("\n");
}

export function applyLayerIteration(prompt, change) {
  const imageIndex = Number(change.imageIndex || 1);
  const layer = change.layer || "第二层:氛围调整层";
  const instruction = change.instruction || "保持产品不变，仅微调指定层";
  return `${prompt}\n\n【局部迭代指令】第 ${imageIndex} 张，仅修改 ${layer}: ${instruction}。其他层级、产品结构、视觉基因和控制变量保持不变。`;
}

function inferReferenceType(referenceKind = "") {
  if (/主图|方图|结构/.test(referenceKind)) return "主图参考-结构复刻";
  return "详情页参考-风格借鉴";
}

function inferTaskType(targetMode = "") {
  if (/点击|CTR|首图/.test(targetMode)) return "8张首图测点击率";
  return "完整 8 张主图";
}

function productKind(category = "") {
  if (/精华|护肤|美妆|面霜|乳液|彩妆|香水/.test(category)) return "beauty";
  if (/椅|家具|家居|办公/.test(category)) return "furniture";
  return "general";
}

function splitSellingPoints(points = "") {
  const items = points
    .split(/[、,，;\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length ? items : ["高颜值", "耐用", "细节质感", "使用省心"];
}

function buildRows(mode, input, sellingPoints) {
  const point = (index) => sellingPoints[index % sellingPoints.length];
  const sceneWord = productKind(input.category) === "beauty" ? "质地" : "空间";
  const templates = {
    scene: [
      ["场景代入", `高级${sceneWord}首图`, "放进理想生活", "一眼看懂品质感", "场景背景", "产品结构/角度/光影"],
      ["人群共鸣", "目标人群使用场景", "为高效时刻而生", "贴合真实使用需求", "人群场景", "产品主体/色温"],
      ["材质感知", `${point(0)} 近景`, "质感看得见", point(0), "材质细节", "主色调/光源方向"],
      ["功能解释", `${point(1)} 展示`, "舒服有支撑", point(1), "功能卖点", "产品角度/文案位置"],
      ["细节证据", `${point(2)} 特写`, "细节更安心", point(2), "证据细节", "统一字体/避让区"],
      ["结果展示", "使用前后情绪差", "久用也轻松", point(3), "使用结果", "画面色温/产品比例"],
      ["场景扩展", "双场景对照", "多场景都合适", "办公居家都好看", "场景组合", "产品主体/光影"],
      ["白底转化", "标准白底图", "核心卖点汇总", "适合平台货架", "信息密度", "白底也保留统一光影"],
    ],
    benefit: [
      ["痛点爆破", "痛点结果对照", "久坐不累", point(0), "痛点文案", "产品结构/角度/光影"],
      ["利益直给", "大字利益钩子", "一坐就放松", point(1), "利益钩子", "主色调/光源方向"],
      ["功能拆解", `${point(0)} 可视化`, point(0), "核心功能可理解", "功能图示", "产品角度/文案位置"],
      ["证据强化", `${point(1)} 细节证据`, point(1), "细节支撑卖点", "证据呈现", "统一字体/避让区"],
      ["对比解释", "普通款对照", "差别一眼懂", point(2), "对比方式", "画面色温/产品比例"],
      ["人群场景", "目标人群场景", "懂你的日常", input.audience || "目标人群", "人群钩子", "产品主体/光影"],
      ["信任兜底", "售后/品质信任", "买前更放心", point(3), "信任信息", "主色调/产品角度"],
      ["白底转化", "货架白底图", "卖点清晰汇总", "适合搜索货架", "标签密度", "白底也保留统一光影"],
    ],
    trust: [
      ["材质信任", `${point(0)} 超近景`, "细节经得起看", point(0), "材质放大", "产品结构/角度/光影"],
      ["工艺信任", `${point(1)} 工艺层`, "做工更扎实", point(1), "工艺证据", "主色调/光源方向"],
      ["功能信任", `${point(2)} 结构解释`, "好用有依据", point(2), "结构解释", "产品角度/文案位置"],
      ["耐用信任", "耐用证据场景", "陪你用更久", point(3), "耐用证据", "统一字体/避让区"],
      ["触感信任", "材质触感氛围", "看起来就舒服", point(0), "感官细节", "画面色温/产品比例"],
      ["专业信任", "参数/证书克制呈现", "专业但不生硬", "重点信息可读", "信任元素", "产品主体/光影"],
      ["风险消除", "购买顾虑回应", "少踩坑更省心", "尺寸/适配/售后", "顾虑信息", "主色调/产品角度"],
      ["白底转化", "平台白底图", "细节卖点汇总", "干净利落", "信息汇总", "白底也保留统一光影"],
    ],
  };

  return templates[mode].map((row, index) => ({
    index: index + 1,
    hookType: row[0],
    visualStrategy: row[1],
    mainCopy: fitCopy(row[2], 8),
    subCopy: fitCopy(row[3], 12),
    testVariable: row[4],
    controlVariable: row[5],
  }));
}

function fitCopy(text, max) {
  const clean = String(text).replace(/\s+/g, "");
  return clean.length > max ? clean.slice(0, max) : clean;
}

function layerTypeForRow(index) {
  if (index <= 2) return "场景层";
  if (index <= 5) return "细节层";
  if (index <= 7) return "功能层";
  return "呼吸层";
}

function avoidAreas(input) {
  const product = productKind(input.category);
  if (product === "beauty") return ["瓶身 Logo", "滴管轮廓", "质地高光"];
  if (product === "furniture") return ["靠背轮廓", "扶手外侧纹理", "底座滚轮"];
  return ["产品 Logo", "核心材质细节", "产品边缘轮廓"];
}

function keyParts(input) {
  const areas = avoidAreas(input);
  return [areas[0], areas[1], areas[2]];
}

function limitNegativeWords(words) {
  return [...new Set(words.filter(Boolean))].slice(0, 10);
}

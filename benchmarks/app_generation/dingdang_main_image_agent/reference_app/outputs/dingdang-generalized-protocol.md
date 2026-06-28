# 叮当 AI 通用生图协议规范

## 0. 总原则

这个应用不应该绑定“8 张主图”或某个品类。它应该是一个通用的电商视觉生成编排器：

- **场景可插拔**：主图、详情页、买家秀、SKU 图、短视频封面、A+ 页面都只是不同 `scene_type`。
- **品类可插拔**：办公椅、精华、服饰、食品、3C、母婴等由 `category_pack` 提供品类知识。
- **平台可插拔**：天猫、淘宝、抖音、拼多多、小红书等由 `platform_policy` 约束风格和合规。
- **输出单元可变**：主图是 8 张图，详情页是多个楼层模块，买家秀是多条 UGC 场景图。
- **生成协议稳定**：无论场景怎么变，Stage1-4 的输入输出结构保持一致。

---

## 1. 输入层协议

### 1.1 InputEnvelope

```json
{
  "job_id": "job_20260624_001",
  "scene_type": "main_image_set | detail_page | buyer_show | sku_image | video_cover | custom",
  "platform": "tmall | taobao | douyin | pdd | xiaohongshu | custom",
  "category": {
    "level1": "家居",
    "level2": "办公家具",
    "level3": "办公椅",
    "custom_tags": ["高客单价", "视觉敏感", "耐用"]
  },
  "objective": {
    "primary": "ctr | conversion | trust | education | ugc_authenticity | launch",
    "secondary": ["ab_test", "brand_consistency", "claim_explanation"]
  },
  "product": {
    "name": "云感商务办公椅",
    "description": "米色皮质办公椅，高靠背，弧形木纹扶手",
    "price_band": "high | mid | low | unknown",
    "selling_points": [
      {
        "text": "人体工学支撑",
        "type": "sensory | functional | trust | price | compliance_sensitive",
        "evidence": "结构图 / 参数 / 用户反馈"
      }
    ],
    "target_audience": "重视居家办公品质的城市白领"
  },
  "assets": {
    "product_images": [
      {
        "id": "asset_product_1",
        "role": "primary_product | sku_variant | detail_closeup",
        "url_or_data_url": "data:image/png;base64,...",
        "lock_level": "strict | medium | loose"
      }
    ],
    "reference_images": [
      {
        "id": "asset_ref_1",
        "role": "style_reference | layout_reference | competitor_reference | ugc_reference",
        "url_or_data_url": "data:image/png;base64,..."
      }
    ],
    "brand_assets": {
      "logo": null,
      "colors": [],
      "fonts": [],
      "forbidden_styles": []
    }
  },
  "constraints": {
    "output_count": 8,
    "aspect_ratio": "1:1",
    "size": "1024x1024",
    "ab_test_mode": "single_variable | multi_hypothesis | none",
    "allow_text_overlay": true,
    "allow_price_label": false,
    "must_keep": ["产品结构", "颜色", "关键 Logo"],
    "must_avoid": ["促销", "价格", "夸张效果"]
  },
  "runtime": {
    "image_provider": "openai | openrouter | custom",
    "image_model": "openai/gpt-image-1",
    "timeout_ms": 120000,
    "stream_events": true
  }
}
```

### 1.2 场景类型协议

| scene_type | 输出单元 | 核心目标 | 变量控制 |
|---|---|---|---|
| `main_image_set` | 8 张主图 / 8 张首图 | CTR、AB 测试、货架点击 | 强单变量 |
| `detail_page` | 多个详情页楼层 | 解释卖点、建立信任、促进转化 | 楼层叙事变量 |
| `buyer_show` | 多张买家秀 / UGC 图 | 真实感、代入感、降低顾虑 | 人群/场景变量 |
| `sku_image` | SKU 规格图 | 识别差异、减少误买 | SKU 差异变量 |
| `video_cover` | 封面图 | 停留、点击、视觉冲击 | 钩子变量 |
| `custom` | 自定义输出单元 | 由用户定义 | 由协议定义 |

---

## 2. Stage 1 需求诊断协议

### 2.1 输入

`Stage1Input = InputEnvelope`

### 2.2 输出 Stage1Diagnosis

```json
{
  "stage": 1,
  "scene_type": "detail_page",
  "task_type": "详情页楼层生图",
  "reference_interpretation": {
    "reference_type": "style_reference | layout_reference | product_structure_reference | ugc_reference",
    "usage_rule": "仅借鉴风格，不复刻商品结构"
  },
  "platform_policy": {
    "platform": "tmall",
    "tone": "克制高级",
    "preferred_patterns": ["材质细节", "场景氛围", "低饱和"],
    "forbidden_patterns": ["强促销", "价格大字报"]
  },
  "category_pack": {
    "category": "办公椅",
    "visual_risks": ["椅背变形", "扶手结构错位", "滚轮消失"],
    "trust_evidence": ["人体工学", "材质", "承重", "售后"]
  },
  "objective_lock": {
    "primary": "conversion",
    "ab_test_mode": "single_variable",
    "success_metric": "CTR | CVR | 加购率 | 咨询率"
  },
  "missing_fields": [],
  "blocking_questions": [
    {
      "id": "task_confirm",
      "type": "single_select",
      "question": "确认生成类型",
      "options": ["完整详情页楼层", "只做首屏详情", "只做卖点模块"]
    }
  ],
  "next_allowed": false
}
```

### 2.3 Stage 1 规则

- 如果 `scene_type` 不明确，必须阻断。
- 如果 `objective.primary` 不明确，必须阻断。
- 如果缺产品图且输出需要严格复刻产品，必须阻断。
- 如果参考图是竞品图，必须标记“结构不可复刻，只能借鉴风格/排版”。
- 如果平台和用户诉求冲突，例如天猫但要求大促销价签，必须输出冲突提示。

---

## 3. Stage 2 创意方案协议

### 3.1 输入

```json
{
  "diagnosis": "Stage1Diagnosis",
  "input_envelope": "InputEnvelope"
}
```

### 3.2 输出 CreativeSchemeSet

```json
{
  "stage": 2,
  "selection_rule": {
    "mode": "single_select",
    "allow_mixing": false,
    "reason": "保持变量可归因"
  },
  "schemes": [
    {
      "scheme_id": "A",
      "name": "轻奢场景型",
      "core_hypothesis": "用户第一眼关心产品放进真实空间后的品质感",
      "hook_strategy": "场景代入",
      "variable_model": {
        "changed_variables": ["场景背景", "单张卖点"],
        "controlled_variables": ["产品角度", "色温", "光源", "文案位置"]
      },
      "output_unit_plan": [
        {
          "unit_id": "unit_01",
          "unit_type": "main_image | detail_floor | buyer_show | sku_panel",
          "hook_type": "场景代入",
          "visual_strategy": "现代办公空间",
          "main_copy": "放进理想生活",
          "sub_copy": "一眼看懂品质感",
          "test_variable": "场景背景",
          "control_variable": "产品角度/光影/色温"
        }
      ],
      "risk_tips": ["若用户强价格敏感，场景型点击可能偏弱"]
    }
  ]
}
```

### 3.3 不同场景的 Stage 2 输出差异

#### 主图

- 输出单元：8 张图。
- 核心变量：首图钩子、场景、卖点表达。
- 强制：方案不可混搭。

#### 详情页

- 输出单元：楼层模块。
- 示例楼层：
  1. 首屏利益锚点
  2. 痛点放大
  3. 核心卖点解释
  4. 细节证据
  5. 场景使用
  6. 参数/对比
  7. 信任兜底
- 变量控制：允许叙事递进，但视觉基因统一。

#### 买家秀

- 输出单元：不同人群/场景的 UGC 图。
- 示例变量：
  - 用户角色：白领 / 宝妈 / 学生 / 新婚家庭
  - 场景：卧室 / 客厅 / 办公桌 / 户外
  - 拍摄质感：手机随拍 / 生活方式 / 轻种草
- 强制：真实感优先，避免过度商业大片感。

---

## 4. Stage 3 策略落地协议

### 4.1 输入

```json
{
  "selected_scheme": "CreativeScheme",
  "input_envelope": "InputEnvelope",
  "diagnosis": "Stage1Diagnosis"
}
```

### 4.2 输出 ExecutionSpec

```json
{
  "stage": 3,
  "visual_constitution": {
    "color_system": {
      "main": "暖米白 70%",
      "secondary": "原木 25%",
      "accent": "深咖 5%",
      "forbidden": ["高饱和霓虹", "硬促销红"]
    },
    "light_system": {
      "direction": "左侧 45 度",
      "temperature": "4500K",
      "shadow": "柔和过渡",
      "surface": "自然柔光"
    },
    "composition_system": {
      "product_ratio": "30%~50%",
      "safe_area": "顶部 15%，底部 20%",
      "angle": "正面微侧 15 度"
    },
    "copy_system": {
      "font_title": "思源黑体 Medium",
      "font_body": "思源黑体 Light",
      "alignment": "左对齐"
    },
    "product_lock": {
      "lock_level": "strict",
      "must_keep": ["产品结构", "关键 Logo", "颜色", "材质纹理"],
      "must_not_change": ["比例", "部件位置", "SKU 颜色"]
    }
  },
  "unit_specs": [
    {
      "unit_id": "unit_01",
      "unit_name": "办公场景首图",
      "layer_type": "scene_layer",
      "visual_spec": {
        "composition": "三分法",
        "background": "现代办公室落地窗",
        "props": ["办公桌", "笔记本", "绿植"],
        "depth": "浅景深"
      },
      "copy_spec": {
        "main": "放进理想生活",
        "sub": "一眼看懂品质感",
        "position": "顶部左侧安全区",
        "avoid": ["靠背轮廓", "扶手纹理", "底座滚轮"]
      },
      "consistency_checks": {
        "color": true,
        "light": true,
        "product_angle": true,
        "copy_safe_area": true
      }
    }
  ],
  "consistency_matrix": [
    {
      "check_item": "产品角度",
      "standard": "正面微侧 15 度",
      "unit_results": {
        "unit_01": true,
        "unit_02": true
      }
    }
  ]
}
```

### 4.3 Stage 3 规则

- 所有“感觉词”必须翻译成数字或可执行参数。
- 输出单元可以不是 8 张，但每个输出单元必须有 `unit_spec`。
- 每个输出单元必须显式声明：
  - 视觉目标
  - 场景/背景
  - 产品锁定规则
  - 文案安全区
  - 变量和控制项
- 任一一致性检查失败，不允许进入 Stage 4。

---

## 5. Stage 4 Prompt 与执行协议

### 5.1 输入

```json
{
  "execution_spec": "ExecutionSpec",
  "runtime": "InputEnvelope.runtime"
}
```

### 5.2 输出 PromptExecutionSet

```json
{
  "stage": 4,
  "prompt_units": [
    {
      "unit_id": "unit_01",
      "prompt_version": "v1",
      "prompt_layers": {
        "visual_gene": "套装视觉基因声明",
        "subject_lock": "产品锚定层",
        "conflict_protocol": "图文冲突以产品图为准",
        "scene_layer": "场景/氛围/光影",
        "info_layer": "文案/标牌/安全区",
        "negative_terms": ["促销", "价格", "霓虹"]
      },
      "final_prompt": "完整出图 Prompt",
      "runtime_request": {
        "provider": "openrouter",
        "model": "openai/gpt-image-1",
        "size": "1024x1024",
        "input_references": ["asset_product_1", "asset_ref_1"]
      }
    }
  ],
  "events": [
    {
      "event": "image.generate.start",
      "unit_id": "unit_01",
      "request_id": "img_xxxxxxxx"
    }
  ]
}
```

### 5.3 通用 Prompt 层协议

无论是主图、详情页还是买家秀，Prompt 都按以下层级生成：

1. **视觉基因层**
   - 统一色调、光照、镜头、画幅、产品角度。
2. **主体锚定层**
   - 产品图绝对优先，锁定结构、比例、颜色、材质、Logo、SKU。
3. **冲突解决层**
   - 文本和产品图冲突时，以产品图为准。
4. **场景/叙事层**
   - 按 `scene_type` 决定是货架主图、详情页楼层、买家秀生活场景等。
5. **信息叠加层**
   - 文案、标牌、参数、对比、评论气泡等。
6. **负面词与合规层**
   - 平台禁忌、品类敏感词、广告法风险、侵权风险。

### 5.4 执行事件协议

```json
{
  "event": "image.generate.start | image.generate.success | image.generate.error | prompt.generated",
  "request_id": "img_xxxxxxxx",
  "job_id": "job_20260624_001",
  "unit_id": "unit_01",
  "provider": "openrouter",
  "model": "openai/gpt-image-1",
  "elapsed_ms": 8421,
  "error": null
}
```

---

## 6. 场景适配示例

### 6.1 主图 8 图

```json
{
  "scene_type": "main_image_set",
  "objective": { "primary": "ctr", "secondary": ["ab_test"] },
  "constraints": {
    "output_count": 8,
    "ab_test_mode": "single_variable",
    "aspect_ratio": "1:1"
  }
}
```

输出单元：8 张主图。  
Stage 2 重点：钩子方案单选。  
Stage 3 重点：统一视觉基因和单变量控制。  
Stage 4 重点：每张图有独立三层 Prompt。

### 6.2 详情页生图

```json
{
  "scene_type": "detail_page",
  "objective": { "primary": "conversion", "secondary": ["education", "trust"] },
  "constraints": {
    "output_count": 7,
    "aspect_ratio": "3:4",
    "ab_test_mode": "none"
  }
}
```

输出单元：详情页楼层。  
推荐楼层：

1. 首屏利益锚点
2. 痛点共鸣
3. 核心卖点解释
4. 材质/工艺证据
5. 使用场景
6. 参数/对比/适配
7. 售后/信任兜底

Stage 2 重点：叙事路线，而不是单张点击钩子。  
Stage 3 重点：楼层节奏、视觉连续性、信息密度。  
Stage 4 重点：每个楼层 Prompt 需要明确模块目标和上下楼层衔接。

### 6.3 买家秀 / UGC 生图

```json
{
  "scene_type": "buyer_show",
  "objective": { "primary": "ugc_authenticity", "secondary": ["trust", "conversion"] },
  "constraints": {
    "output_count": 6,
    "aspect_ratio": "3:4",
    "allow_text_overlay": false,
    "ab_test_mode": "multi_hypothesis"
  }
}
```

输出单元：不同用户角色的生活化图片。  
推荐变量：

- 人群：白领、宝妈、学生、情侣、家庭。
- 场景：客厅、卧室、办公桌、户外、通勤。
- 拍摄质感：手机随拍、自然光、轻微构图不完美。

Stage 2 重点：真实感路线。  
Stage 3 重点：不要过度商业大片感，保留生活痕迹。  
Stage 4 重点：Prompt 中应限制“棚拍、过度精修、广告海报感”。

---

## 7. 适配器接口

新增任何场景，只需要实现一个 SceneAdapter：

```ts
interface SceneAdapter {
  sceneType: string;
  requiredInputs(): string[];
  diagnose(input: InputEnvelope): Stage1Diagnosis;
  generateSchemes(input: InputEnvelope, diagnosis: Stage1Diagnosis): CreativeSchemeSet;
  buildExecutionSpec(input: InputEnvelope, scheme: CreativeScheme): ExecutionSpec;
  buildPromptUnits(spec: ExecutionSpec): PromptExecutionSet;
}
```

新增任何品类，只需要实现一个 CategoryPack：

```ts
interface CategoryPack {
  category: string;
  sensoryPoints: string[];
  functionalPoints: string[];
  trustPoints: string[];
  visualRisks: string[];
  complianceRisks: string[];
  recommendedScenes: string[];
  productLockParts: string[];
}
```

新增任何平台，只需要实现一个 PlatformPolicy：

```ts
interface PlatformPolicy {
  platform: string;
  tone: string;
  preferredPatterns: string[];
  forbiddenPatterns: string[];
  copyRules: string[];
  negativeTerms: string[];
}
```

---

## 8. 推荐演进路线

1. 先把当前 `main_image_set` 做成第一个 `SceneAdapter`。
2. 再增加 `detail_page`，复用 Stage1/3/4，只替换 Stage2 的输出单元和叙事规则。
3. 再增加 `buyer_show`，重点增加 UGC 真实感规则和人群场景变量。
4. 最后把 `CategoryPack` 独立成 JSON 配置，让新品类不需要改代码。

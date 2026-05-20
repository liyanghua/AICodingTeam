# 小红书采集 Agent 五框架对比实施计划

## Summary
目标是基于 `init.md` 的 AI-native 工程生产线，做一个可复现的浏览器自动化评测工程：同一采集任务、同一输出 Schema、五个框架独立实现，最后产出稳定性、完整性、风控友好度、成本和工程可维护性的对比报告。

安全边界先锁定：不做验证码破解、指纹伪装、代理轮换、反检测绕过、私有接口逆向或批量压测。小红书官方 `robots.txt` 当前对通用 User-Agent 是 `Disallow:/`，所以生产化采集必须走授权接口、合作数据源或书面许可；本计划只做低频、人工登录、内部评测用途。若出现验证码、验证、封禁、异常登录提示，Agent 立即暂停并记录为风险事件。

## Key Interfaces
统一 CLI：

```bash
growth-dev xhs auth --framework playwright-mcp
growth-dev xhs run --framework stagehand --keyword "露营" --top-n 20
growth-dev xhs benchmark --suite pilot
growth-dev xhs report --run-id 2026-05-20-xhs-browser-benchmark
```

统一输入：

```json
{
  "keyword": "露营",
  "top_n": 20,
  "candidate_pool": 100,
  "max_comments_per_note": 500,
  "mode": "headed_low_frequency",
  "profile_dir": ".local/browser-profiles/xhs"
}
```

统一输出 `XhsNote`：

```json
{
  "note_id": "...",
  "url": "...",
  "title": "...",
  "body": "...",
  "author": {"display_name": "...", "profile_url": "..."},
  "counts": {"likes": 0, "collects": 0, "comments": 0, "shares": 0},
  "media": [{"type": "image|video", "visible_url": "...", "screenshot_path": "..."}],
  "comments": [{"text": "...", "like_count": 0, "replies": []}],
  "extraction_meta": {"framework": "...", "complete": true, "risk_events": []}
}
```

统一排序策略：如果页面没有可靠的“按评论数排序”入口，就先按关键词搜索采集候选池，再解析候选卡片评论数，在本地排序取 TOP N。

## Execution Checklist
- [ ] 建立工程任务包：生成 `task.yaml`、`context.md`、`prd.md`、`tech_spec.md`、`ui_spec.md`、`tdd_cases.md`、`review_checklist.md`、`coding_prompt.md`。
- [ ] 写入仓库约束：`AGENTS.md` 明确禁止反风控绕过、私有接口逆向、自动验证码处理、未授权批量采集和无关重构。
- [ ] 搭建 Harness：Python CLI 负责任务编排、配置加载、运行记录、结果归档、评分报告；TypeScript/Python adapter 通过 stdin/stdout JSON 契约接入。
- [ ] 建立本地 Mock 小红书页面：包含搜索框、候选笔记、评论数、图文笔记、视频笔记、一级评论、二级评论、加载更多、空状态和异常状态。
- [ ] 实现通用评测器：校验 JSON Schema，计算稳定性、完整性、风险事件、运行时间、人工介入次数、LLM token 成本、失败原因。
- [ ] 实现登录管理：每个框架只打开可视化浏览器；用户手动扫码或输入验证码；session 保存在 `.local/browser-profiles/xhs`，不保存密码。
- [ ] 实现 Playwright MCP adapter：通过 MCP server 控制浏览器，使用 accessibility snapshot 做定位，作为确定性基线。
- [ ] 实现 Stagehand adapter：用 `observe/act/extract` 做搜索、点击和结构化抽取，用 Zod Schema 约束输出。
- [ ] 实现 Skyvern adapter：使用 Skyvern 本地或 API 工作流完成同一任务，关闭任何自动验证码/规避型能力，挑战出现即暂停。
- [ ] 实现 HyperAgent adapter：基于 Playwright + 自然语言命令完成搜索和详情页抽取，记录 action cache/replay 能力对稳定性的影响。
- [ ] 实现 browser-use adapter：用 Python Agent + Browser profile 完成任务，增加自定义工具负责结果写入和 Schema 校验。
- [ ] 先跑 Mock 测试：五个 adapter 都必须在本地 Mock 页面拿到 100% Schema 合格输出。
- [ ] 再跑 Pilot：真实小红书只跑 `keyword=露营, top_n=3`，每个框架一次，要求无验证码、无异常登录、无阻断。
- [ ] 通过 Gate 后跑 Benchmark：采用混合评测，端到端模式测完整流程，固定 URL 模式测同一批 20 篇笔记的详情抽取完整性。
- [ ] 生成最终报告：包含五框架雷达图、失败样例截图、字段缺失表、风险事件日志、推荐排序和下一步生产化建议。

## Evaluation Criteria
稳定性：成功完成率、崩溃次数、重试次数、定位失败次数、平均耗时。

完整性：标题、正文、作者、互动数、图片、视频信息、一级评论、二级评论的字段覆盖率；评论完整度以“页面可见/可加载评论数”为分母。

风控友好度：验证码、异常登录、频繁操作提示、页面阻断、账号限制都记为风险事件；正式 TOP 20 评测的硬门槛是 pilot 风险事件为 0。

工程性：adapter 代码量、可调试性、复现难度、token/API 成本、是否容易沉淀成 `Hermes Skill`。

预期初判：Playwright MCP 最适合作为确定性基线；Stagehand 适合结构化抽取和页面变化容忍；Skyvern 适合复杂长流程但黑盒感更强；HyperAgent 适合 TypeScript/Playwright 体系内快速试验；browser-use 适合 Python 侧快速 Agent 原型。

## Test Plan
- Unit：中文数字解析，如 `1.2万`、`999+`；Schema 校验；评论树去重；排序逻辑；评分器。
- Integration：五个 adapter 分别跑 Mock 页面，验证搜索、打开详情、展开评论、二级评论抽取、媒体记录。
- Pilot：真实站点 `top_n=3`，只验证端到端可行性和风险事件。
- Benchmark：`top_n=20`，同一关键词、同一账号、低频串行执行，不并发。
- Review Gate：输出报告必须包含失败原因，不允许只给成功样例。

## Assumptions
默认使用本地可视化浏览器和人工登录，不使用云端 stealth、代理轮换、验证码解决服务。默认只保存文本、可见媒体 URL、截图证据和结构化元数据；不批量下载原始视频或图片文件。默认实验数据仅用于内部框架评测，不做公开再分发。

参考资料：Playwright MCP 官方说明、Stagehand 官方说明、Skyvern 官方说明、HyperAgent 官方说明、browser-use 官方说明、小红书 `robots.txt`、小红书开放平台文档。

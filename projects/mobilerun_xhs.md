基于当前 fork 的 https://github.com/droidrun/mobilerun 仓库，不要从 0 新建移动自动化框架。

请在仓库中新增 `extensions/xhs_collector` 扩展模块，实现小红书搜索结果采集 POC。

核心要求：
1. 复用 mobilerun 的手机控制、UI tree、screenshot、tap/swipe/type、structured output 能力。
2. 不修改 mobilerun 核心 Runtime，除非必须暴露 public API。
3. 所有小红书业务逻辑放在 `extensions/xhs_collector`。
4. 新增 CLI：`mobilerun-xhs collect-search --keyword "桌布 防水 防油" --max-notes 10 --max-swipes 5`。
5. 实现固定流程：打开小红书 → 搜索关键词 → 抽取当前屏幕卡片 → 滑动 → 继续抽取 → 去重 → 输出 report。
6. 每一屏保存 screenshot、UI tree 和抽取结果。
7. 输出结构化 JSON report。
8. 遇到登录、验证码、风控、网络错误时停止，并返回明确状态。
9. 不要做登录绕过、验证码破解、接口逆向和高频采集。
10. 先实现 MockClientAdapter 单元测试，再接真实 MobilerunClientAdapter。

交付：
- extensions/xhs_collector 完整代码
- README
- prompts
- models
- task runner
- CLI
- mock tests
- 示例输出 JSON

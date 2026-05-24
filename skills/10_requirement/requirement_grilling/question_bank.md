# Question Bank

Use these questions selectively. Ask only when the answer changes scope, data shape, UI behavior, tests, or risk.

## 业务目标

- 这次需求最终要改善哪个业务结果？
- 如果只能交付一个最小版本，必须保留什么？
- 成功后用户、产品、工程各自能看到什么证据？

## 用户与流程

- 谁是主要用户？谁只是观察者、审核者或维护者？
- 用户从哪里开始，到哪里算完成？
- 哪些步骤必须由人确认，哪些可以由 AI 自动推进？

## 范围边界

- v1 明确包含什么？
- 哪些看起来相关但本次不做？
- 是否需要兼容已有 CLI、Dashboard、domain pack 或 run artifact？

## 数据对象

- 核心对象叫什么？字段和状态有哪些？
- 哪些字段必须结构化保存，哪些只是展示文本？
- 是否有敏感信息、provider key、登录态或外部平台数据边界？

## UI 与状态

- 页面需要展示哪些业务状态：未开始、处理中、已完成、需要处理、等待确认？
- empty/loading/error/success 分别怎么呈现？
- 默认给业务用户看什么？哪些放到高级/工程详情？

## 验收

- 哪些行为必须有自动化测试？
- 哪些只需要人工走查或 review checklist？
- 失败时用户应该看到什么原因和下一步？

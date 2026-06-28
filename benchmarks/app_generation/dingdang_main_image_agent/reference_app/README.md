# 叮当 AI 电商主图设计智能体

本地 Web 应用，基于 `dingdang-prd.md` 实现四阶段主图工作流，并支持 OpenAI / OpenRouter 双图片生成供应商：

1. 需求诊断
2. 创意方案单选
3. 视觉基准卡与 8 张规划卡
4. 三层 Prompt 与真实图片生成

## 运行

```bash
cp .env.example .env
```

推荐使用 OpenRouter 时，在 `.env` 中填写：

```bash
IMAGE_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-your-key-here
OPENROUTER_IMAGE_MODEL=openai/gpt-image-1
IMAGE_REQUEST_TIMEOUT_MS=120000
```

使用 OpenAI 时，改成：

```bash
IMAGE_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
```

启动：

```bash
npm start
```

默认地址：

```text
http://127.0.0.1:5173
```

局域网访问：

服务默认监听 `0.0.0.0:5173`。启动日志会输出 `lanUrl`，同一局域网内其它设备访问这个地址即可，例如：

```text
http://192.168.1.20:5173
```

只允许本机访问时，在 `.env` 中设置：

```bash
HOST=127.0.0.1
```

## 出图

- 先上传产品图。
- 可选上传参考图。
- 点击“生成 Prompt”后，可单张生成，也可点击“生成全部图片”。
- API Key 只在 Node 服务端读取，不会暴露到浏览器。
- OpenRouter 模式请求 `https://openrouter.ai/api/v1/images`，参考图通过 `input_references` 传入。
- 外部图片 API 超过 `IMAGE_REQUEST_TIMEOUT_MS` 未返回时，服务端会中断请求并把错误返回到前端，避免界面一直停在“生成中”。

## 生图卡住排查

1. 前端日志出现“节点开始”但没有“节点结束”时，通常是服务端还在等外部图片 API。
2. 默认超时是 120000ms。可以在 `.env` 调小，例如 `IMAGE_REQUEST_TIMEOUT_MS=30000`。
3. 如果超时后仍频繁失败，优先检查模型名、OpenRouter 余额、图片模型是否支持 `input_references`。

## 验证

```bash
npm test
npm run check
```

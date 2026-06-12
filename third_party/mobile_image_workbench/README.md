# 移动端图片采集工作台

面向业务和产品人员的本地移动端图片采集工作台。前端使用 Vue 3 + TypeScript，后端复用 `third_party/xhs_collector` 的 Android 小红书确定性采集链路。

## 安全边界

- 只支持用户手动登录小红书。
- 不采集账号密码，不绕验证码，不使用私有接口。
- 遇到登录、验证码、权限或风控状态时停止或标记为需要人工处理。

## 启动

Mac mini 长期部署请使用：

```bash
bash ../mobile_deploy/mac-mini/install_workbench_launchd.sh
```

脚本会安装 Python venv、构建前端、生成 macOS LaunchAgent，并监听 `0.0.0.0:8765` 供内网访问。首次运行会生成 `.env` 示例，请填写 `MWB_CLOUD_SERVER_URL`、`MWB_CLOUD_SYNC_TOKEN`、`MWB_COLLECTOR_ID` 和 `DASHSCOPE_API_KEY` 后重跑。

本地开发启动：

```bash
cd third_party/mobile_image_workbench
npm install
npm run build
PYTHONPATH=".:../xhs_collector" ../xhs_collector/.venv/bin/python -m mobile_image_workbench serve --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765`。

配置文件模式优先使用“选择项目文件夹”：选择一个同时包含 Excel 和图片的目录，例如：

```text
买家秀场景图/
  桌垫买家秀_TOP10关键词组合.xlsx
  1d3c....png
  xxx.jpg
```

工作台会自动找到唯一的 `.xlsx/.xlsm` 配置文件，并把同目录图片放到 Excel 旁边解析；不需要业务用户手动理解 `image_path` 的相对路径。

开发前端时可以另开一个终端：

```bash
npm run dev
```

## CLI

## 关键词采集入口状态

当前已验证的关键词采集能力在 `xhs_collector` CLI：

```bash
python3 -m xhs_collector run-keyword --keyword "<关键词>" --top-n <N> --config config/xhs_collector.json --mode deterministic
```

`mobile_image_workbench` 的关键词-only UI job entry 已纳入 `xhs_mobile_collection` domain pack 的允许修改边界，后续实现应复用该 collector keyword-only 能力，并继续保持手动登录、不绕验证码、不使用私有接口的安全边界。

配置文件模式：

```bash
PYTHONPATH=".:../xhs_collector" ../xhs_collector/.venv/bin/python -m mobile_image_workbench run \
  --mode config_file \
  --input "../../input_image/买家秀场景图/桌垫买家秀_TOP10关键词组合.xlsx" \
  --image-top-n 10 \
  --keyword-top-n 4 \
  --keyword-result-top-n 5
```

单图模式：

```bash
PYTHONPATH=".:../xhs_collector" ../xhs_collector/.venv/bin/python -m mobile_image_workbench run \
  --mode single_image \
  --input path/to/reference.png \
  --image-top-n 10
```

本机场景标签：

```bash
export DASHSCOPE_API_KEY="your-dashscope-api-key"

PYTHONPATH=".:../xhs_collector" ../xhs_collector/.venv/bin/python -m mobile_image_workbench tag-scenes \
  --runs-root runs \
  --category "桌垫" \
  --limit 200
```

`tag-scenes` 默认使用千问 `qwen-vl-max`，默认兼容模式地址为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。如需覆盖，可传 `--model` 或设置 `DASHSCOPE_BASE_URL`。

同步当前 job 到云端素材中心：

```bash
PYTHONPATH=".:../xhs_collector" ../xhs_collector/.venv/bin/python -m mobile_image_workbench sync-cloud \
  --runs-root runs \
  --server-url "$MWB_CLOUD_SERVER_URL" \
  --token "$MWB_CLOUD_SYNC_TOKEN" \
  --collector-id "$MWB_COLLECTOR_ID" \
  --job-id "<job_id>"
```

## 默认值

- 单图片/批量图片：每张原图默认采集 10 张图搜结果，不跑关键词二次搜索。
- 配置文件：每张原图默认图搜采集 10 张，取前 4 条关键词，每条关键词采集 5 张。

## 产物

每个 job 存在 `runs/<job_id>/`，其中 `collector_runs/<run_id>/` 包含：

- `manifest.json`
- `step_events.jsonl`
- `risk_events.jsonl`
- `results.html`
- `results.csv`
- `results_images.zip`

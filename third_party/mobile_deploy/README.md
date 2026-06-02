# Mobile Image Collection Deployment

This deployment is split into two machines.

- Mac mini: phone collection, collection workbench, Qwen-VL scene tagging, cloud sync.
- Cloud server: asset center Python API and frontend, backed by PostgreSQL and Aliyun OSS.

## 两套环境

- Local validation：在当前机器验证素材中心、工作台 API、云端 PG/OSS 连接和同步逻辑。使用本地 Python/venv 和本地 env 文件，不代表实机采集可生产。
- Mac mini production workbench：通过 SSH 远程部署到 Mac mini，由 Mac mini 自己的 Python、ADB、XHS 登录状态和 LaunchAgent 执行实机采集。

本地 `.env*` 不会通过远程部署同步到 Mac mini。真实 secret 只放在当前机器或远程 Mac mini 的私有 env 文件中；如果 secret 包含 `$`，建议用单引号包起来，例如 `DASHSCOPE_API_KEY='abc$def'`。

## 本地验证

1. Prepare the local asset center cloud profile. `mobile_asset_center` requires Python `<3.14`:

```bash
cd third_party/mobile_asset_center
python3.12 -m venv .venv-asset-center
. .venv-asset-center/bin/activate
python -m pip install -e '.[cloud]'
python -m mobile_asset_center serve \
  --env-file .env.asset.local-cloud \
  --host 127.0.0.1 \
  --port 8876 \
  --static-root frontend
```

2. Prepare the local workbench profile:

```bash
cp third_party/mobile_deploy/mac-mini/workbench.local.env.example third_party/mobile_image_workbench/.env.local
cd third_party/mobile_image_workbench
python3 -m mobile_image_workbench serve \
  --env-file .env.local \
  --host 127.0.0.1 \
  --port 8765 \
  --static-root frontend/dist
```

3. Verify local APIs and cloud connectivity:

```bash
curl http://127.0.0.1:8876/api/health
curl http://127.0.0.1:8765/api/doctor
```

## Mac mini

1. Connect the Android phone by USB and confirm:

```bash
adb devices
```

2. Create the remote Mac mini workbench env on the Mac mini:

```bash
cp third_party/mobile_deploy/mac-mini/workbench.mac-mini.env.example \
  third_party/mobile_image_workbench/.env.mac-mini
```

Fill `MWB_CLOUD_*`, `DASHSCOPE_API_KEY`, `MWB_PYTHON_BIN`, and Android paths on the Mac mini.

3. Install the workbench LaunchAgent:

```bash
cd /path/to/repo
MWB_ENV_FILE=third_party/mobile_image_workbench/.env.mac-mini \
  bash third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh
```

If `MWB_ENV_FILE` is omitted, the installer keeps backward compatibility and uses `third_party/mobile_image_workbench/.env`.

4. Fill the selected workbench env with:

```bash
MWB_CLOUD_SERVER_URL=http://asset-center.internal
MWB_CLOUD_SYNC_TOKEN=the-same-token-as-cloud-server
MWB_COLLECTOR_ID=mac-mini-01
DASHSCOPE_API_KEY=your-dashscope-key
```

5. Rerun the installer and verify on the Mac mini:

```bash
launchctl print gui/$(id -u)/com.ontology.mobile-image-workbench
curl http://127.0.0.1:8765/api/doctor
```

Open `http://<mac-mini-ip>:8765` from the internal network.

## 从当前机器远程部署 Mac mini

Mac mini SSH 信息不要写到 `third_party/mobile_asset_center/.env.asset.cloud`。那份文件只用于云端素材中心连接 PG 和 OSS。

1. Create the remote deploy profile:

```bash
cp third_party/mobile_deploy/mac-mini/remote.env.example third_party/mobile_deploy/mac-mini/.env.remote
```

2. Fill `third_party/mobile_deploy/mac-mini/.env.remote` with:

```bash
MWB_MAC_MINI_SSH_TARGET=user@mac-mini-ip
MWB_MAC_MINI_REMOTE_ROOT=/Users/user/mobile-runtime
MWB_MAC_MINI_WORKBENCH_ENV_FILE=/Users/user/mobile-runtime/third_party/mobile_image_workbench/.env.mac-mini
MWB_MAC_MINI_SSH_KEY_PATH=/Users/you/.ssh/mac-mini-deploy
MWB_MAC_MINI_SSH_PORT=22
```

Password auth is supported as a fallback:

```bash
MWB_MAC_MINI_SSH_PASS=your-password
```

Password mode requires `sshpass` on the machine that starts deployment. The old names `MAC_MINI_USER`, `MAC_NINI_PASS`, and `RES_DIR` are accepted only for temporary compatibility; new setups should use `MWB_MAC_MINI_*`.

3. Run one-click remote deployment from the current repo:

```bash
cd /path/to/repo
python3 -m mobile_image_workbench deploy-mac-mini --json
```

If `mobile_image_workbench` is not on `PYTHONPATH`, run from the repo root with:

```bash
PYTHONPATH=third_party/mobile_image_workbench/backend \
  python3 -m mobile_image_workbench deploy-mac-mini --json
```

You can also open the workbench admin page and click `远程部署 Mac mini`, or call:

```bash
curl -X POST http://127.0.0.1:8765/api/admin/deploy/mac-mini \
  -H "Authorization: Bearer $MWB_ADMIN_TOKEN"
```

4. Verify on the Mac mini:

```bash
ssh user@mac-mini-ip 'launchctl print gui/$(id -u)/com.ontology.mobile-image-workbench'
curl http://mac-mini-ip:8765/api/doctor
```

The remote deployment keeps excluding `.env*` from rsync. Create or edit `MWB_MAC_MINI_WORKBENCH_ENV_FILE` on the Mac mini itself before deployment.

## 云服务器

1. Install Python 3.11+, rsync, and nginx.

2. Install the cloud asset center:

```bash
cd /path/to/repo
sudo bash third_party/mobile_deploy/server/install_asset_center_systemd.sh
```

3. Fill `/opt/mobile_asset_center/asset-center.env` with PostgreSQL, OSS, and `ASSET_CENTER_SYNC_TOKEN`.

4. Rerun the installer and verify:

```bash
systemctl status mobile-asset-center
curl http://127.0.0.1:8876/api/health
curl "http://127.0.0.1:8876/api/categories"
```

Open the server address in the internal network to view the asset center.

## Sync Acceptance

1. Run a collection job on the Mac mini workbench.
2. Wait until the job is `completed` or `partial`.
3. Click `打标签并同步云端`.
4. Verify cloud data:

```bash
curl "http://<asset-center-host>/api/categories"
curl --get "http://<asset-center-host>/api/scenes" --data-urlencode "category=桌垫"
curl --get "http://<asset-center-host>/api/assets" --data-urlencode "category=桌垫" --data-urlencode "limit=5"
```

PostgreSQL should contain rows in `source_images`, `assets`, and `asset_tags`; OSS should contain `original/...` and `collected/...` objects.

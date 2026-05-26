# Mobile Image Collection Deployment

This deployment is split into two machines.

- Mac mini: phone collection, collection workbench, Qwen-VL scene tagging, cloud sync.
- Cloud server: asset center Python API and frontend, backed by PostgreSQL and Aliyun OSS.

## Mac mini

1. Connect the Android phone by USB and confirm:

```bash
adb devices
```

2. Install the workbench LaunchAgent:

```bash
cd /path/to/repo
bash third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh
```

3. Fill `third_party/mobile_image_workbench/.env` with:

```bash
MWB_CLOUD_SERVER_URL=http://asset-center.internal
MWB_CLOUD_SYNC_TOKEN=the-same-token-as-cloud-server
MWB_COLLECTOR_ID=mac-mini-01
DASHSCOPE_API_KEY=your-dashscope-key
```

4. Rerun the installer and verify:

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
MWB_MAC_MINI_SSH_KEY_PATH=/Users/you/.ssh/mac-mini-deploy
MWB_MAC_MINI_SSH_PORT=22
```

Password auth is supported as a fallback:

```bash
MWB_MAC_MINI_SSH_PASS=your-password
```

Password mode requires `sshpass` on the machine that starts deployment. The old names `MAC_MINI_USER`, `MAC_NINI_PASS`, and `RES_DIR` are accepted only for temporary compatibility; new setups should use `MWB_MAC_MINI_*`.

3. Open the workbench admin page and click `远程部署 Mac mini`, or call:

```bash
curl -X POST http://127.0.0.1:8765/api/admin/deploy/mac-mini \
  -H "Authorization: Bearer $MWB_ADMIN_TOKEN"
```

4. Verify on the Mac mini:

```bash
ssh user@mac-mini-ip 'launchctl print gui/$(id -u)/com.ontology.mobile-image-workbench'
curl http://mac-mini-ip:8765/api/doctor
```

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

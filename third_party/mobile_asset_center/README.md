# Mobile Asset Center

云端素材中心只负责素材入库、检索、预览和下载；本机采集器仍连接手机并把采集结果写到本地。

## 配置 Profile

素材中心后端通过 `ASSET_CENTER_PROFILE` 切换存储环境：

- `local`：SQLite + 本地对象目录，默认值，适合开发和离线验收。
- `cloud`：PostgreSQL + 阿里云 OSS，适合正式素材中心和多终端同步。

示例配置文件：

- `.env.asset.local.example`
- `.env.asset.cloud.example`

真实 `.env` 不要提交到代码库。

## 本地存储模式

```bash
python -m mobile_asset_center serve \
  --env-file .env.asset.local \
  --host 127.0.0.1 \
  --port 8876 \
  --data-root third_party/mobile_asset_center/data \
  --static-root third_party/mobile_asset_center/frontend \
  --sync-token dev-token
```

## 云 PG + OSS 模式

`.env.asset.cloud` 至少需要：

```bash
ASSET_CENTER_PROFILE=cloud
ASSET_CENTER_STORAGE_PROVIDER=aliyun_oss
ASSET_CENTER_DB_DSN=postgresql://asset_user:password@pg.example.com:5432/asset_center
ALIYUN_OSS_BUCKET=your-bucket
ALIYUN_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
ALIYUN_OSS_ACCESS_KEY_ID=your-access-key-id
ALIYUN_OSS_ACCESS_KEY_SECRET=your-access-key-secret
ASSET_CENTER_SYNC_TOKEN=your-sync-token
```

启动：

```bash
python -m mobile_asset_center serve \
  --env-file .env.asset.cloud \
  --host 127.0.0.1 \
  --port 8876 \
  --static-root third_party/mobile_asset_center/frontend
```

服务启动时会自动确保 PostgreSQL 表结构存在。

云服务器长期部署请使用：

```bash
sudo bash ../mobile_deploy/server/install_asset_center_systemd.sh
```

脚本会安装 Python venv、生成 systemd service，并在安装了 Nginx 时写入反代配置。首次运行会生成 `/opt/mobile_asset_center/asset-center.env` 示例，请填写 PG、OSS 和 `ASSET_CENTER_SYNC_TOKEN` 后重跑。

## 本机同步

```bash
python -m mobile_image_workbench sync-cloud \
  --runs-root third_party/mobile_image_workbench/runs \
  --server-url http://127.0.0.1:8876 \
  --token dev-token \
  --collector-id mac-01
```

`sync-cloud` 只依赖 `--server-url`，不关心服务端当前是 local 还是 cloud。图片文件写对象存储，元数据写数据库；同品类下按 `category + contentSha256` 去重，不同品类允许复用同一张图片。

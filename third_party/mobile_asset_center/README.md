# Mobile Asset Center

云端素材中心只负责素材入库、检索、预览和下载；本机采集器仍连接手机并把采集结果写到本地。

## 本地启动云端服务开发版

```bash
python -m third_party.mobile_asset_center.backend.mobile_asset_center serve \
  --host 127.0.0.1 \
  --port 8876 \
  --data-root third_party/mobile_asset_center/data \
  --static-root third_party/mobile_asset_center/frontend \
  --sync-token dev-token
```

## 本机同步

```bash
python -m mobile_image_workbench sync-cloud \
  --runs-root third_party/mobile_image_workbench/runs \
  --server-url http://127.0.0.1:8876 \
  --token dev-token \
  --collector-id mac-01
```

图片文件写对象存储，元数据写数据库。开发版使用本地文件系统和 SQLite；生产环境替换为阿里云 OSS 和 PostgreSQL。

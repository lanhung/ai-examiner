# 从 v0.2 升级到 v0.3

## 兼容性

v0.3 新增表，不修改 v0.2 已有表列：

- evidence_assets
- visual_analyses
- prompt_versions
- background_jobs
- joint_analyses

应用启动时自动 `create_all`。

## 推荐步骤

```bash
cd ai-examiner-mvp-v0.2.0
./deploy/backup.sh  # 如旧版没有此脚本，直接备份 data 目录
cp -a data ../data-backup-v02

cd ../ai-examiner-mvp-v0.3.0
cp ../ai-examiner-mvp-v0.2.0/.env .env
cp -a ../ai-examiner-mvp-v0.2.0/data ./data
docker compose up -d --build
```

检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/prompts
```

## 旧文档

v0.2 文档没有 EvidenceAsset。最简单的方式是重新上传。旧答辩和 Golden Dataset 不受影响。

## 回滚

```bash
docker compose down
rm -rf data
cp -a ../data-backup-v02 data
cd ../ai-examiner-mvp-v0.2.0
docker compose up -d --build
```

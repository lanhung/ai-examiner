# Backup and Restore

## Shell backup

```bash
./deploy/backup.sh
```

## Python entrypoint

```bash
uv run ai-examiner-backup
```

## Verify archive

```bash
tar -tzf data/backups/ai-examiner-*.tar.gz | head
```

## Restore

```bash
./deploy/restore.sh BACKUP.tar.gz
```

API Key 不包含在数据备份中。`.env` 应单独安全保存。

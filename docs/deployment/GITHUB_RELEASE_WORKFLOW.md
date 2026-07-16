# GitHub version-preservation workflow

## One-time repository setup

Create a private repository named `ai-examiner` under the `lanhung` account. Do not initialize it with a README if uploading the full existing tree.

On Vultr:

```bash
cd ai-examiner-mvp-v0.3.0
git init
git branch -M main
git add .
git commit -m "release: AI Examiner v0.3.0"
git remote add origin git@github.com:lanhung/ai-examiner.git
git push -u origin main
git tag -a v0.3.0 -m "AI Examiner v0.3.0"
git push origin v0.3.0
```

## Required exclusions

The included `.gitignore` excludes:

- `.env` and API keys;
- SQLite databases;
- uploads and generated evidence;
- exports and backups;
- Python caches and virtual environments.

Confirm before every push:

```bash
git status --short
git diff --cached --check
grep -RInE 'sk-(proj|ant)-' . --exclude-dir=.git || true
```

## Per-version workflow

```bash
git checkout -b release/v0.4.0
# add code and documentation
git add .
git commit -m "release: AI Examiner v0.4.0"
git push -u origin release/v0.4.0
```

Open a pull request into `main`, run CI, merge, then tag:

```bash
git checkout main
git pull --ff-only
git tag -a v0.4.0 -m "AI Examiner v0.4.0"
git push origin v0.4.0
```

## Recommended release assets

Attach these to each GitHub Release:

- full source ZIP;
- Python wheel;
- Python source distribution;
- SHA-256 checksums;
- release notes;
- migration guide;
- project status report.

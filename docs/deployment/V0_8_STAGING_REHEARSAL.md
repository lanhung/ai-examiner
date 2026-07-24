# v0.8 Staging and Compose Rehearsal

## Status

The rehearsal harness is implemented on `develop/v0.8.0`. It has not been executed
on the current Windows host because Docker is unavailable there. Do not mark the
Compose or Vultr gate passed until the commands below complete on a Docker host.

## Isolated Compose rehearsal

From the repository root:

```bash
chmod +x deploy/rehearse-v08-compose.sh
./deploy/rehearse-v08-compose.sh
```

The script:

1. accepts only a rehearsal project name beginning with
   `ai-examiner-v08-rehearsal`;
2. creates a temporary host data directory and environment file;
3. forces `MODEL_PROVIDER=mock`;
4. validates and builds the base plus production Compose files;
5. migrates an isolated SQLite database to Alembic head;
6. starts API, worker and Redis on port `18080`;
7. checks `/health` and `/api/templates/health`;
8. runs `ai-examiner-evaluate-templates` inside the image;
9. creates and inspects a SQLite-safe backup;
10. removes only the isolated project, volumes and temporary directory.

Override the port when needed:

```bash
REHEARSAL_PORT=18081 ./deploy/rehearse-v08-compose.sh
```

The script intentionally does not use OpenAI or DashScope credentials.

## Provider evidence

Provider probes are separate from the Compose rehearsal:

```bash
uv run ai-examiner-probe-template-providers \
  --document ./examples/sample_research.md \
  --profiles qwen:qwen-plus,openai:gpt-5.4-mini
```

Generated reports belong under `data/` and must not be committed.

## Attach provider evidence to deterministic report

```bash
uv run ai-examiner-evaluate-templates \
  --output ./data/v08-template-evaluation.json \
  --provider-probe ./data/v08_qwen_template_probe.json \
  --provider-probe ./data/v08_openai_template_probe.json
```

This releases only the provider contract-sample gates. Scenario relevance and
deployment rehearsals remain independent. Relevance evidence is documented in
`docs/evaluation/V0_8_SCENARIO_RELEVANCE_CORPUS.md`.

## Vultr staging sequence

Use a separate staging worktree or directory. Do not point the production service
at `develop/v0.8.0`.

```bash
git fetch --tags --prune origin
git clone --branch develop/v0.8.0 \
  https://github.com/lanhung/ai-examiner.git \
  /opt/ai-examiner-v08-staging
cd /opt/ai-examiner-v08-staging
cp .env.example .env
chmod 600 .env
```

Run the isolated rehearsal first:

```bash
./deploy/rehearse-v08-compose.sh
```

Only after it passes, configure staging credentials and a non-production port in
`.env`, then:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  build

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  run --rm --no-deps ai-examiner \
  alembic upgrade head

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --remove-orphans
```

Verify:

```bash
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/health
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/api/templates/health
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

## Production promotion gate

Production remains on `main` or an immutable accepted tag. Promotion is prohibited
while any of these are held:

- isolated Compose rehearsal;
- Vultr staging upgrade and rollback;
- backup restore verification against a staging copy.

Cross-provider blind scenario relevance passed in Increment N for three complete
30-case templates. It is no longer a held promotion gate.

Never use `docker compose down -v` during a normal production upgrade.

# v0.3 Product Scope

## In scope

- Preserve all v0.2 text-exam and dataset-benchmark functions.
- Parse PDF/PPTX/DOCX/TXT/Markdown.
- Build page/slide evidence indexes with coordinates and preview files.
- Inspect page images with configured multimodal models.
- Compare 2–8 related documents.
- Link Golden cases to evidence assets.
- Version and activate Prompt definitions.
- Freeze/deprecate/diff Golden Dataset versions.
- Run long operations through Celery/Redis.
- Show Provider readiness and estimated model cost.
- Deploy on one Vultr server using Docker Compose.

## Explicitly out of scope

- OCR for scanned PDFs.
- Pixel-perfect PowerPoint or Word rendering.
- Mathematical proof verification.
- Real-time speech, interruption, or voice scoring.
- User login and tenant isolation.
- PostgreSQL, S3, or Kubernetes.
- Automated degree/recruitment decisions.

## Definition of done

- Existing v0.2 tests pass.
- PDF, PPTX, and DOCX fixtures create evidence assets.
- Page preview and highlight endpoints return files.
- Mock visual and joint agents complete end-to-end.
- Async Golden Dataset completes in eager test mode.
- Dataset can be frozen and diffed.
- Prompt activation changes AgentContext instructions.
- Docker Compose defines API, worker, and Redis.
- Deployment, migration, backup, and API documents are present.

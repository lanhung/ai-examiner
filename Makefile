.PHONY: install install-providers run test lint demo smoke corpus eval-templates probe-template-providers clean

install:
	uv sync --extra dev

install-providers:
	uv sync --extra dev --extra providers

run:
	uv run uvicorn ai_examiner.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest --cov=ai_examiner --cov-report=term-missing

lint:
	uv run ruff check .

demo:
	MODEL_PROVIDER=mock uv run uvicorn ai_examiner.main:app --host 0.0.0.0 --port 8000

smoke:
	uv run python scripts/smoke_test.py

corpus:
	uv run ai-examiner-build-corpus --input ./papers --output ./golden_exports

eval-templates:
	uv run ai-examiner-evaluate-templates --output ./data/template-evaluation-report.json

probe-template-providers:
	uv run ai-examiner-probe-template-providers --document ./examples/sample_research.md

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage data/*.db dist build *.egg-info

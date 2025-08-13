.PHONY: setup lint test fmt md check-md ci

setup:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pre-commit install

fmt:
	ruff check . --fix
	ruff format .
	pre-commit run mdformat --all-files || true

lint:
	ruff check .
	mypy src
	npx markdownlint "**/*.md" --config .markdownlint.json

test:
	pytest -q

md:
	npx markdownlint "**/*.md" --fix --config .markdownlint.json

check-md:
	npx markdownlint "**/*.md" --config .markdownlint.json

ci:
	make fmt && make lint && make test && make check-md

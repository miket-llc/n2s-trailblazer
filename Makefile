.PHONY: setup lint test fmt md check-md precommit

setup:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pre-commit install

fmt:
	ruff check . --fix
	black src tests
	mdformat $(shell git ls-files '*.md')

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

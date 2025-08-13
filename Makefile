.PHONY: setup lint test fmt precommit

setup:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pre-commit install

lint:
	ruff check .
	mypy src

fmt:
	ruff check . --fix
	black src tests

test:
	pytest -q

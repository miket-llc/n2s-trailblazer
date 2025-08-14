.PHONY: setup lint test fmt md check-md ci db.up db.down db.wait

setup:
	python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pre-commit install

fmt:
	ruff check . --fix
	ruff format .
	pre-commit run mdformat --all-files || true

lint:
	ruff check .
	mypy src
	npx markdownlint "**/*.md" --ignore "var/**" --ignore "archive/**" --config .markdownlint.json

test:
	pytest -q

md:
	npx markdownlint "**/*.md" --ignore "var/**" --ignore "archive/**" --fix --config .markdownlint.json

check-md:
	npx markdownlint "**/*.md" --ignore "var/**" --ignore "archive/**" --config .markdownlint.json

ci:
	make fmt && make lint && make test && make check-md

# Database targets
db.up:
	docker compose -f docker-compose.db.yml up -d

db.down:
	docker compose -f docker-compose.db.yml down

db.wait:
	@echo "Waiting for PostgreSQL to be ready..."
	@for i in $$(seq 1 30); do \
		if docker compose -f docker-compose.db.yml exec postgres pg_isready -U trailblazer -d trailblazer >/dev/null 2>&1; then \
			echo "PostgreSQL is ready!"; \
			exit 0; \
		fi; \
		echo "Attempt $$i/30: PostgreSQL not ready yet, waiting..."; \
		sleep 2; \
	done; \
	echo "PostgreSQL failed to become ready after 60 seconds"; \
	exit 1

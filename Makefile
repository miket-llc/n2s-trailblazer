.PHONY: setup lint test fmt md check-md ci db.up db.down db.wait reembed.openai reembed.openai.pilot reembed.openai.all embed.monitor embed.kill enrich.all

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
	TB_TESTING=1 TRAILBLAZER_DB_URL="postgresql+psycopg2://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer" pytest -q

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

# OpenAI corpus re-embedding (CLI-based)
reembed.openai:
	@echo "🚀 Starting OpenAI corpus re-embedding..."
	@echo "Prerequisites:"
	@echo "  - OPENAI_API_KEY set in .env"
	@echo "  - TRAILBLAZER_DB_URL set in .env"
	@echo "  - Database running (make db.up)"
	@echo "  - Virtual environment activated"
	@echo
	@echo "Running: trailblazer embed load with OpenAI provider"
	@scripts/reembed_corpus_openai.sh

reembed.openai.pilot:
	@echo "[PILOT] building runs file (top 2)"
	@ls -1t var/runs | grep -E '_full_adf$$|_dita_full$$' \
	  | while read rid; do \
	      [ -f var/runs/$$rid/enrich/enriched.jsonl ] && \
	      echo $$rid:$$$$(wc -l < var/runs/$$rid/enrich/enriched.jsonl); \
	    done | sort -t: -k2 -nr | sed -n '1,2p' > var/temp_runs_to_embed.txt
	@WORKERS=$${WORKERS:-2} bash scripts/embed_dispatch.sh var/temp_runs_to_embed.txt

# run with 2 workers by default
# override: WORKERS=3 make reembed.openai.all
reembed.openai.all:
	@echo "[ALL] building runs file (all enriched runs)"
	@ls -1t var/runs | grep -E '_full_adf$$|_dita_full$$' \
	  | while read rid; do \
	      [ -f var/runs/$$rid/enrich/enriched.jsonl ] && \
	      echo $$rid:$$$$(wc -l < var/runs/$$rid/enrich/enriched.jsonl); \
	    done | sort -t: -k2 -nr > var/temp_runs_to_embed.txt
	@WORKERS=$${WORKERS:-2} bash scripts/embed_dispatch.sh var/temp_runs_to_embed.txt

embed.monitor:
	@INTERVAL=$${INTERVAL:-15} bash scripts/monitor_embedding.sh

embed.kill:
	@bash scripts/kill_embedding.sh

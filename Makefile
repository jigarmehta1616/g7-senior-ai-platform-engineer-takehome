# Windows without make: use the python commands shown in each target (also in README).
PY ?= python

.PHONY: install run console console-dev test unit contract evals lint newman mcp demo docker clean

install:            ## create venv deps (editable)
	$(PY) -m pip install -e ".[dev,agent]"

run:                ## API :8080 + mock upstreams :8081
	$(PY) scripts/run_local.py

console:            ## typecheck + build the React console into frontend/dist
	cd frontend && npm ci && npm run build

console-dev:        ## Vite dev server with HMR on :5173 (proxies the API)
	cd frontend && npm run dev

test:               ## unit + integration + contract + MCP evals
	$(PY) -m pytest

unit:
	$(PY) -m pytest tests/unit
contract:
	$(PY) -m pytest -m contract
evals:
	$(PY) -m pytest -m evals -v

lint:
	$(PY) -m ruff check src mcp tests scripts
	$(PY) -m mypy

newman:             ## run the collection against a running stack
	npx --yes newman run postman/support-platform.postman_collection.json -e postman/local.postman_environment.json

mcp:                ## MCP server over stdio (acts for the support-lead persona)
	COPILOT_PERSONA=support-lead $(PY) -m support_copilot

demo:               ## LLM agent demo (needs ANTHROPIC_API_KEY)
	$(PY) mcp/demo/agent_demo.py

docker:
	docker compose up --build

clean:
	rm -rf var .pytest_cache .ruff_cache frontend/dist

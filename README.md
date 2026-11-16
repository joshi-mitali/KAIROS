# KAIROS

Multi-agent research for Indian equities: **collect → analyze → debate → decide → propose → remember**.

Four specialist analysts review market, sentiment, news and fundamentals evidence. New web runs fetch fresh sources; legacy CLI research can read saved datasets. Bull and Bear researchers debate their findings, a research manager produces a verdict, and a trader creates a **simulated BUY / HOLD / SELL proposal** using the verdict, risk preference and persistent memory. KAIROS does not place live orders.

Default watchlist: RELIANCE, TCS, INFY, HDFCBANK and ICICIBANK. The web workspace supports exchange-aware NSE/BSE discovery.

## Start here

[Requirements audit](docs/requirements_audit.md) · [Verification record](docs/testing.md)


- [Agent flow and architecture](docs/agent_flow.md): the diagram and what each agent does.
- [Project structure and editing guide](docs/project_structure.md): where code and configuration belong.
- [Agent definitions](kairos_config/agents/): roles, goals and backstories for all eight agents.
- [Task definitions](kairos_config/prompts/tasks.jsonc): prompts, agent references and expected outputs.

## Workspace

```bash
pip install -e '.[dev]'
cp kairos_config/.env.example .env  # first setup only; preserve an existing file
npm --prefix web ci
npm --prefix web run build
python -m kairos.web.app
```

Open `http://127.0.0.1:8000`. Research fetches fresh evidence into a separate directory per run, then executes ADK market tools → specialist reports → standard A2A → CrewAI Bull/Bear/manager → grounded proposal. Unavailable fresh sources stop the run visibly. Existing CLI paths retain offline research support; the web UI has no archived-data mode.

The trading workspace provides NSE/BSE search, candlestick/line charts and actual observed quote points. Quotes poll MegaBull every 15 seconds and history refreshes every minute. Polling is not exchange tick streaming; provider delays and timestamps are shown. Order previews never submit. An exact, expiring, session-bound approval is required for each virtual order.

Editable JSONC lives together under **`kairos_config/`**: `agents/`, `prompts/`, `providers/`, `security.jsonc`, `observability.jsonc`, and the environment template. Python code lives in `kairos/`; React code in `web/`; tests in `tests/`; launchers and maintenance in `scripts/`; retained snapshots in `data/archive/`.

[Tracing and safeguards](docs/observability.md) · [Render package, deployment deferred](docs/deployment.md) · [TradingAgents comparison](docs/tradingagents_comparison.md).

## Install

Use Python 3.12 or 3.13 for the CrewAI stack. Create a fresh environment on your machine rather than copying a virtual environment between operating systems.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp kairos_config/.env.example .env
```

Configure existing provider credentials in `.env`. Research prefers Groq when configured and otherwise uses Gemini. Without successful model execution, KAIROS labels its rule-based output `DETERMINISTIC_FALLBACK`. Data acquisition still requires usable datasets or functioning sources; offline model fallback does not fabricate market data.

## Prepare data separately

```bash
python -m kairos.cli discover-mcp
python -m kairos.pipeline.refresh
python -m kairos.cli validate
```

To refresh saved quotes, news and Reddit periodically:

```bash
python -m kairos.pipeline.scheduler --interval 300
```

The scheduler does not run agents. Its default domains omit historical prices and fundamentals. Analysis reads saved datasets, preferring Parquet over CSV.

## Run research

```bash
python -m kairos
python -m kairos --ticker RELIANCE --risk conservative
python -m kairos --all --risk neutral
python -m kairos --trader-only --risk aggressive
```

Installed commands: `kairos`, `kairos-data`, `kairos-refresh`, `kairos-schedule`. Existing `python main.py`, `python run.py`, `python dataphase1_logic.py` and `python scripts/scheduler.py` launchers remain available.

`--trader-only` consumes existing `data/processed/phase2_verdicts.json`. Default exports under `data/processed/` include verdicts, proposals, debate transcripts and a memory audit. Memory uses PostgreSQL when available and SQLite otherwise. Proposals remain unexecuted/PENDING.

Set `KAIROS_DEBATE_ROUNDS=3` to change the default two-round debate.

## Edit agent behavior

Edit `kairos_config/agents/<agent>.jsonc` for `role`, `goal` and `backstory`. Research agents also expose `settings.verbose` and `settings.allow_delegation`. Edit `kairos_config/prompts/tasks.jsonc` for task descriptions and expected outputs. JSONC supports comments and trailing commas; restart the process after editing cached definitions.

Python owns schemas, calculations, task context, retries, memory and debate sequencing. This is a hybrid JSONC-driven application, not a standalone `crewai run` project. Researchers use actual CrewAI Agent/Task objects; the historically named `adk_analysts` call model SDKs directly.

The configuration split follows the [CrewAI first-crew guide](https://docs.crewai.com/v1.15.41/en/guides/crews/first-crew), adapted to KAIROS's dynamic debate and specialist pipeline.

## Verify changes

Configuration and agent behavior checks (use a disposable copy to preserve generated reports):

```bash
python -m pytest tests/test_agent_configuration.py tests/test_phase2_agents.py \
  tests/test_multi_round_debate.py tests/test_trader_agent.py tests/test_memory_mcp.py
```

Some existing tests write reports or memory, and collector/live-integration tests call external services. The full suite is available with `python -m pytest`; it is not an offline-only suite.

The [historical Phase 1 README](docs/archive/phase1-readme.md), [data architecture](docs/architecture_phase1.md) and [interoperability plan](docs/a2a_crewai_adk_plan.md) provide background. The current agent-flow document and source code describe implemented behavior.

# Traces, safeguards and execution evidence

Langfuse uses the US host, `https://us.cloud.langfuse.com`. Enable `KAIROS_LANGFUSE_ENABLED=true` and configure both project keys on the backend. The installed official [Langfuse skill](https://github.com/langfuse/skills) guided the integration.

The root `analyze-equity` chain contains specialist spans, ADK workflow/tool calls, CrewAI tasks, memory retrieval and trade proposal synthesis. OpenInference instruments ADK and CrewAI; the Langfuse OpenAI wrapper records Groq model usage. Selected inputs and structured outputs are masked before export. All configured pool keys are redacted individually. Tags and release labels live in `kairos_config/observability.jsonc`; labels identify KAIROS without changing unrelated Langfuse projects.

Project API keys cannot rename the Langfuse project itself; organization-level access is required for that separate operation. The configured project can still receive correctly labeled KAIROS traces.

Callbacks append actual starts, reports, task outputs, guard checks and failures to the local event ledger, which the browser receives over SSE. Completed runs retain their events. The ADK state inspector exposes both MCP outputs and the report used in the handoff. Research completion does not prove that a remote trace was received: verify it in Langfuse. SDK exports can fail during network outages.

Groq Prompt Guard 2 86M screens untrusted news, sentiment, fundamental text and retrieved memory before model synthesis. Its threshold and bounded overlapping chunks live in `kairos_config/security.jsonc`. A failed or unavailable enabled scan blocks downstream synthesis. `NOT_RUN` is explicit when scanning is disabled or credentials are absent. Injection detection is probabilistic; schemas, deterministic grounding and order approval remain separate checks.

Groq keys rotate only after rate limiting, with a cooldown per key and a bounded number of attempts. Keys on the same account may share quota; adding keys does not increase that account quota. No automatic loop submits paper orders.

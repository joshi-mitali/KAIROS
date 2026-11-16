# KAIROS configuration

Edit this folder to change agent identities, prompts, provider setup and trace labels.

- `agents/`: eight JSONC roles, goals and backstories.
- `prompts/tasks.jsonc`: task instructions and expected output.
- `providers/mcp_servers.json`: external market-data tool configuration.
- `observability.jsonc`: stable application name, release and trace tags.
- `.env.example`: copy to the project-root `.env` and add credentials locally.

Secrets stay in the ignored `.env`, never in JSONC or frontend code. Restart after changing cached definitions. Python loaders remain under `kairos/config/`.

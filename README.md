# dvad-agent-native

> Multi-LLM adversarial review as an agent-callable checkpoint. Proof of thinking, shipped with the work.

## What it is

An MCP server + Claude Code skill that lets your coding agent run an adversarial multi-model review — at the plan stage, at the implementation stage, before saying "done." The handoff that lands on your screen shows what three models disagreed about, what the agent revised, and what it left for your judgment.

Advisory, not a gate. Fast (sub-30s lite mode). Zero-config from API keys in your environment.

## Install

```
pipx install dvad-agent-native
dvad-agent install
```

That's it. The second command registers the MCP server with Claude Code and drops a skill into `~/.claude/skills/dvad.md`.

## Requirements

- Python 3.11+
- At least one of: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`
- Claude Code (or any MCP-compatible client)
- **Platforms:** Linux, macOS, Windows via WSL. Native Windows is a v2 target.

## Demo

*Coming soon.*

## How it works

See [`docs/spec.v3.md`](docs/spec.v3.md) for the full product spec and [`docs/plan.v3.md`](docs/plan.v3.md) for the implementation plan.

## CLI

The `dvad-agent` CLI exists as development infrastructure — it is not the product surface. The product is the MCP tool call from inside your agent session. The CLI lets you probe providers, scan artifacts for secrets, check your config, and run reviews without the agent harness in the way.

## License

MIT.

# JARVIS

JARVIS is a local-first, modular autonomous assistant foundation with an
injected AI-provider boundary for future Raspberry Pi LLM support.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `jarvis/main.py` — CLI entry point and one-shot goal mode.
- `jarvis/core/` — assistant orchestration.
- `jarvis/agent/` — Brain, Planner, Agent Executor, Code Agent, and self-improvement.
- `jarvis/memory/` — local JSON memory manager.
- `jarvis/tools/` — tool protocol, registry, execution, and verification.
- `jarvis/sandbox/` — restricted workspace paths and bounded Python compilation.
- `jarvis/rollback/` — file checkpoints and restoration.
- `jarvis/system/` — read-only system monitoring.
- `jarvis/network/` — explicit network authorization policy.
- `jarvis/plugins/` — explicit plugin discovery and factory registration.
- `tests/` — standard-library `unittest` coverage for the architecture.

## Architecture decisions

- No AI provider is bundled: autonomous planning and code generation fail explicitly until a real provider is injected.
- `AIProvider` is the adapter contract for a future local Raspberry Pi model; the core never depends on an external API.
- Plans are structured data, not free-form text. Tools return structured results and must verify each step.
- Code changes are allow-listed `.py` files, parsed before write, compile-tested in the sandbox, and checkpointed for rollback.
- Self-improvement produces proposals and requires explicit approval before applying changes.

## Product

JARVIS supports local memory, registered tools, structured autonomous goals,
bounded execution and retries, failure recovery, restricted Python code changes,
system observation, explicit network policy, and controlled plugin loading.

## User preferences

- Keep the project standard-library-only until an external provider or dependency is explicitly requested.

## Gotchas

- `python -m unittest discover -s tests -v` is the test command.
- `goal <objective>` requires a real injected `Brain`; the default `UnavailableBrain` must not fabricate AI output.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details

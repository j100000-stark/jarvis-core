# JARVIS

JARVIS is a clean V0.1 foundation for a modular autonomous assistant. It is
local-first, uses only Python's standard library, and deliberately has no
external APIs or third-party dependencies yet.

## Run

Interactive mode:

```bash
python -m jarvis
```

One-shot mode:

```bash
python -m jarvis --once "time"
python -m jarvis --once "remember My preferred briefing time is 09:00"
python -m jarvis --once "recall briefing"
```

The `jarvis` command is also available after installing the project:

```bash
python -m pip install -e .
jarvis
```

## V0.1 architecture

```text
jarvis/
├── main.py             CLI entry point
├── core/               Assistant orchestration and conversation flow
├── memory/             Local JSON-backed memory
├── tools/              Tool protocol, registry, and safe built-ins
├── config/             Environment-backed runtime settings
├── sandbox/            Workspace path and timeout boundaries
├── recovery/           Recoverable error recording
├── agent/              Brain, planner, executor, code agent, and improvement flow
├── rollback/           Restricted file checkpoints and restoration
├── system/             Read-only host monitoring
├── network/            Explicit network authorization policy
├── plugins/            Explicit plugin discovery and registration
└── agent/local_provider.py  Local HTTP/process model provider boundary
```

## Built-in commands

- `help` — list available commands
- `time` — show the current UTC time
- `echo <text>` — return text
- `remember <fact>` — persist a local memory in `data/memory.json`
- `recall [query]` — search local memories
- `status` — show runtime state
- `goal <goal>` — plan and execute a high-level goal through a configured Brain
- `exit` — close the session

## Autonomous architecture

JARVIS separates intelligence from execution:

1. A configured `Brain`/`AIProvider` turns a high-level goal into structured
   plan steps. No provider is bundled, so the default refuses to invent a plan.
2. `Planner` validates the plan against shared models.
3. `AgentExecutor` selects only registered tools, executes bounded retries, and
   requires verification for every step.
4. `MemoryManager`, `RecoveryManager`, and `SystemMonitor` provide context,
   incident tracking, and read-only health information.
5. `CodeAgent` accepts only complete `.py` files in an allow-list, parses and
   compiles them in the sandbox, and restores a pre-change checkpoint on failure.
6. `SelfImprovementManager` creates proposals but requires explicit approval
   before applying code changes.

The `NetworkManager` and `PluginManager` are policy boundaries: external
networking is disabled by default and plugins are never imported merely because
they exist on disk.

## Local model provider

`LocalAIProvider` is ready for a real model runtime without changing JARVIS
Core. It accepts either:

- A loopback HTTP endpoint such as
  `http://127.0.0.1:11434/api/generate`
- A local executable process invoked without a shell

The runtime must return structured JSON for plans, code changes, and improvement
proposals. JARVIS does not turn ordinary prose into a successful result.

Enable the endpoint adapter:

```bash
export JARVIS_LOCAL_PROVIDER_ENABLED=true
export JARVIS_LOCAL_PROVIDER_MODE=endpoint
export JARVIS_LOCAL_ENDPOINT=http://127.0.0.1:11434/api/generate
export JARVIS_LOCAL_MODEL_NAME=your-local-model
export JARVIS_LOCAL_PROVIDER_TIMEOUT=30
python -m jarvis --goal "organize my notes"
```

Or configure a local process adapter:

```bash
export JARVIS_LOCAL_PROVIDER_ENABLED=true
export JARVIS_LOCAL_PROVIDER_MODE=process
export JARVIS_LOCAL_PROCESS_COMMAND="python -m my_local_runtime"
export JARVIS_LOCAL_MODEL_NAME=your-local-model
```

The process adapter uses `shell=False`, and endpoint mode accepts only
`localhost`, `127.0.0.1`, or `::1`.

## Configuration

All settings have local defaults. Optional environment variables:

- `JARVIS_NAME`
- `JARVIS_VERSION`
- `JARVIS_DATA_DIR`
- `JARVIS_MEMORY_FILE`
- `JARVIS_MAX_MEMORY_ITEMS`
- `JARVIS_SANDBOX_TIMEOUT`
- `JARVIS_AUTONOMOUS_MAX_RETRIES`
- `JARVIS_LOCAL_PROVIDER_ENABLED`
- `JARVIS_LOCAL_PROVIDER_MODE` (`endpoint` or `process`)
- `JARVIS_LOCAL_ENDPOINT`
- `JARVIS_LOCAL_PROCESS_COMMAND`
- `JARVIS_LOCAL_MODEL_NAME`
- `JARVIS_LOCAL_PROVIDER_TIMEOUT`

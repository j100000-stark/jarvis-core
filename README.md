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
└── recovery/           Recoverable error recording
```

## Built-in commands

- `help` — list available commands
- `time` — show the current UTC time
- `echo <text>` — return text
- `remember <fact>` — persist a local memory in `data/memory.json`
- `recall [query]` — search local memories
- `status` — show runtime state
- `exit` — close the session

## Configuration

All settings have local defaults. Optional environment variables:

- `JARVIS_NAME`
- `JARVIS_VERSION`
- `JARVIS_DATA_DIR`
- `JARVIS_MEMORY_FILE`
- `JARVIS_MAX_MEMORY_ITEMS`
- `JARVIS_SANDBOX_TIMEOUT`

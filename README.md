# JARVIS — Modular Autonomous Agent Architecture

JARVIS is a Python-based modular autonomous AI assistant with a resilience layer, defensive security subsystem, multi-agent orchestration, and a mobile-friendly web interface.

---

## Architecture

```
JARVIS
├── Core (Assistant)          — orchestration, conversation, status
├── Agent Layer
│   ├── Brain / AIProvider    — abstraction contract; REAL local LLM interface
│   ├── LocalAIProvider       — REAL local model (HTTP or process transport)
│   ├── UnavailableBrain      — default; explicitly refuses without a provider
│   ├── DemoBrain             — DEMO ONLY; deterministic scripted plans
│   ├── Planner               — validates brain-generated plans
│   ├── AgentExecutor         — executes plans through the safe tool boundary
│   ├── AgentOrchestrator     — multi-agent goal routing
│   ├── CodeAgent             — generate, sandbox-test, checkpoint code changes
│   └── SelfImprovementManager — proposals + capability requests (approval required)
├── Resilience Layer
│   ├── WatchdogManager       — cooperative liveness checks
│   ├── CrashRecoveryManager  — incident records + restart budget
│   ├── ServiceSupervisor     — bounded restarts + exponential backoff
│   ├── HealthCheckManager    — component health aggregation
│   └── StateRecoveryManager  — JSON state snapshots before risky operations
├── Network
│   ├── NetworkManager        — URL policy / allow-list (V0.1 base)
│   └── NetworkRecoveryManager — state machine: ONLINE/DEGRADED/OFFLINE/LOCAL_ONLY/RECOVERING
├── Security (defensive only; authorized local systems)
│   ├── SecurityCommander     — orchestrate security agents, produce unified report
│   ├── SecuritySentinel      — read-only local system monitoring + anomaly detection
│   ├── SecurityInvestigator  — correlate events, build timeline, assign risk
│   ├── SecurityDefender      — safe defensive actions behind explicit safety gate
│   └── SecurityTestAgent     — local posture checks (no exploitation)
├── Memory, Sandbox, Rollback, System Monitor, Plugin Manager
└── Web Interface
    ├── React/Vite mobile-first frontend (iPhone/iPad safe-area)
    ├── TypeScript API server (Express + OpenAPI-generated Zod contracts)
    └── System panel: health, network, recovery, security, agent activity, DEMO indicator
```

---

## What is REAL

| Component | Status |
|---|---|
| LocalAIProvider | **REAL** — connects to a local LLM via HTTP loopback or subprocess |
| WatchdogManager | **REAL** — cooperative liveness checks on registered services |
| CrashRecoveryManager | **REAL** — records incidents, enforces restart budgets |
| ServiceSupervisor | **REAL** — bounded restarts with exponential backoff |
| NetworkRecoveryManager | **REAL** — TCP connectivity probes + state machine |
| SecuritySentinel | **REAL** — reads /proc, local hostname, network interfaces |
| SecurityTestAgent | **REAL** — reads filesystem permissions and environment keys |
| SecurityInvestigator | **REAL** — correlates actual sentinel events |
| SecurityDefender | **REAL** — logs and preserves evidence; destructive actions require approval |
| Web interface | **REAL** — polls live Python subprocess; no mocked data |

## What is DEMO

| Component | Note |
|---|---|
| DemoBrain | Scripted deterministic plans — always labelled **DEMO MODE — NO REAL AI CONNECTED** |
| Demo plans | Show goal → agent selection → safe execution → report flow |

Demo mode is activated by `JARVIS_DEMO_MODE=true`. The interface shows a prominent yellow DEMO MODE banner.

## What is FUTURE (not implemented)

| Capability | Note |
|---|---|
| Real LLM runtime | LocalAIProvider interface is ready; plug in Ollama or similar |
| Voice / microphone | Placeholder button in UI; no audio processing |
| Camera / vision | Not implemented |
| Local Wi-Fi access point | LocalAccessPoint / LocalNetworkFallback stubs in `network/recovery.py` |
| Raspberry Pi hardware | All hardware stubs are abstract base classes |
| Cellular connectivity | Interface defined; not implemented |
| Satellite connectivity | Interface defined; not implemented |
| Sensors / actuators | Not implemented |

---

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `JARVIS_NAME` | JARVIS | Display name |
| `JARVIS_VERSION` | v0.1.0 | Version string |
| `JARVIS_DATA_DIR` | data | Data directory path |
| `JARVIS_MAX_MEMORY` | 100 | Max memory items |
| `JARVIS_SANDBOX_TIMEOUT` | 5.0 | Sandbox timeout (seconds) |
| `JARVIS_MAX_RETRIES` | 3 | Max autonomous retries |
| `JARVIS_LOCAL_PROVIDER_ENABLED` | false | Enable local AI provider |
| `JARVIS_LOCAL_PROVIDER_MODE` | http | `http` or `process` |
| `JARVIS_LOCAL_ENDPOINT` | http://localhost:11434 | Local model HTTP endpoint |
| `JARVIS_LOCAL_PROCESS_COMMAND` | — | Command to launch local model process |
| `JARVIS_LOCAL_MODEL_NAME` | local | Model name |
| `JARVIS_LOCAL_PROVIDER_TIMEOUT` | 30.0 | Provider timeout (seconds) |
| `JARVIS_DEMO_MODE` | false | Enable deterministic demo brain |

**Local endpoint restrictions**: Only `localhost`, `127.0.0.1`, or `::1` are accepted as local provider endpoints.

---

## Running

```bash
# Interactive session
python -m jarvis

# Single message
python -m jarvis --once "status"

# Execute a goal
python -m jarvis --goal "Check whether my computer is behaving normally."

# JSON system report (used by web interface)
python -m jarvis --system-report

# Demo mode
JARVIS_DEMO_MODE=true python -m jarvis
```

---

## Security principles

- All security capabilities operate **only on explicitly authorized local systems**.
- Defensive actions (stop process, disable service, isolate interface) require **explicit approval** (`approved=True`).
- SecurityTestAgent raises `AuthorizationError` if no target has been explicitly authorized.
- No offensive capabilities, no credential theft, no external network scanning.
- SelfImprovementManager **cannot self-grant permissions** — all new capabilities generate a `CapabilityRequest` requiring operator approval.

---

## Tests

```bash
python -m unittest discover -s tests -v
```

133 tests across:
- `test_agent.py` — Brain, Planner, Executor, CodeAgent, Rollback, SelfImprovement
- `test_boundaries.py` — Sandbox, Rollback, SystemMonitor, NetworkPolicy, Plugins
- `test_existing_modules.py` — Memory, Recovery, Tools, Assistant, Brain injection
- `test_local_provider.py` — LocalAIProvider transport, JSON parsing, config, restrictions
- `test_resilience.py` — Watchdog, CrashRecovery, Supervisor, HealthCheck, StateRecovery
- `test_network_recovery.py` — Network state transitions, offline mode, recovery, backoff
- `test_security.py` — Sentinel, Investigator, Defender safety gates, TestAgent, Commander
- `test_orchestration.py` — Multi-agent orchestration, capability approval
- `test_demo.py` — DemoBrain, DemoProvider, DEMO label verification

---

## Web Interface

The mobile-first interface is built with React + Vite and served through a TypeScript Express API server. All endpoints call the Python JARVIS runtime through a controlled subprocess.

API endpoints:
- `GET /api/jarvis/status` — runtime and brain provider state
- `POST /api/jarvis/messages` — send a goal to JARVIS
- `GET /api/jarvis/system` — comprehensive system state (health, network, recovery, security, agent activity, demo mode)

The frontend displays:
- **Runtime status** — connection, provider, version, external APIs
- **Conversation** — chat UI with goal submission, disabled microphone placeholder
- **System status rail** (desktop) — component health, network state, recovery incidents, security summary, agent activity, DEMO MODE banner
- **No-provider error state** — clear message when AI provider is not configured

# Team task split (4 members)

Team: **Nabeel Wagle**, **LIU Jiayu**, **JI Guangning**, **GU Tianyang**.

Each member owns one vertical slice of the platform: their own files, their own commits, and their own section of the architecture document.

| # | Member | Slice | Main files |
|---|---|---|---|
| 1 | Nabeel Wagle | Core runtime: settings, schemas, message bus, LLM client (HKGAI/DeepSeek), agent loop, tool gateway, app wiring, CLI, run traces, integration | `core/`, `llm/`, `agents/`, `tools/gateway.py`, `app.py`, `cli.py`, `settings.py` |
| 2 | LIU Jiayu | Orchestration and HITL: routing, planning, negotiation, parallel execution, retry/re-plan, approval policy | `orchestration/`, `human/` |
| 3 | JI Guangning | Tools and sandbox: web search/fetch, file CRUD, Python exec/tests, git commit/push, workspace isolation, Docker backend | `tools/search.py`, `tools/files.py`, `tools/python_exec.py`, `tools/git.py`, `sandbox/`, `docker/` |
| 4 | GU Tianyang | Memory/evolution and evaluation: reflection, TF-IDF retrieval, usefulness scoring, playbooks, eval runner, checks, metrics, dev task set | `memory/`, `evaluation/` |

## Schedule

| Date | Who | Work |
|---|---|---|
| Nov 7 | Nabeel Wagle | Core runtime and baseline modules |
| Nov 8–9 | LIU Jiayu | Routing, HITL policy, negotiation, parallelism, retry/re-plan; docs |
| Nov 9–10 | JI Guangning | Web search, git, file tools, sandbox; code execution, Docker, tests; docs |
| Nov 11–12 | GU Tianyang | Memory evolution and evaluation harness; dev task set; docs |
| Test set release (3 weeks before deadline) | Everyone | Run `mas eval`, analyse failure modes, fix, re-run |
| Week 13 | Everyone | Presentation; each member presents their slice |

## Git rules
1. `git pull origin main` before starting any work.
2. Only change the files of your own slice, unless the team agrees otherwise.
3. Run `.venv/bin/pytest -q` before every push.
4. Never commit `.env`, API keys or `runtime/`.
5. Log important decisions in `docs/contribution_log.md` (date | name | what | why).

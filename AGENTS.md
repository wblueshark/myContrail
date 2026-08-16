# Contrail — Development Rules

Rules for everyone who changes this repository: human developers and AI coding
agents alike. One source, every tool. If your tool has its own rules file, that
file only points here (see [Tool adapters](#9-tool-adapters)).

Companion document: [ARCHITECTURE.md](ARCHITECTURE.md) — what the system is made
of, which module does what, and the API index.

---

## 1. Precedence

When two sources disagree, the higher one wins:

| # | Source | Role |
|---|---|---|
| 1 | `docs/design/**` | **The only authority.** Product, data contract, algorithms, architecture. |
| 2 | An approved Change Request | Authorises one specific deviation or addition. |
| 3 | This file | How to work. |
| 4 | `ARCHITECTURE.md` | A derived view of the code. Descriptive, never normative. |
| 5 | Existing code | Precedent for style, not for correctness. |

`ARCHITECTURE.md` describing something the design forbids is a bug in
`ARCHITECTURE.md`. Never "fix" the design to match the code.

> **`docs/` is not in this repository.** The design documents are derived from
> thirteen years of one person's real location history, so they are kept out of
> the public repo and distributed separately. Ask the maintainer for the design
> set and unpack it at `docs/` — it is gitignored, so it will not be committed
> back. Without it you can still fix bugs and refactor against the existing
> code, but you cannot implement a new behaviour: there is nothing to implement
> it against.

---

## 2. Non-negotiables

Violating any of these is worse than shipping nothing.

- **`Sample/` is real personal data** — 13 years of one person's actual location
  history. It is gitignored. Never commit it, never paste coordinates from it
  into a document, a commit message, a Change Request, or a chat log.
- **`data/` and `.env` are gitignored** and stay that way. `data/` holds imported
  uploads, generated thumbnails and exports.
- **Privacy fences are the one unacceptable class of bug.** Any path that emits
  geometry — export, tiles, data dump — must apply fences server-side.
  `POST /exports` returns `422` when the scope intersects a fence and
  `fence_actions` is absent. Never relax that check to make a client simpler.
- **No filesystem path may enter an HTTP request body.** Photo directories are
  chosen by the OS-native picker and referenced by a one-shot `pick_token`.
  `reject_path_fields()` rejects any request carrying `path`, `directory`,
  `root`, `scan_path` or `abs_path`. This makes path traversal structurally
  impossible; do not reintroduce a path field "temporarily".
- **All coordinates are WGS-84.** There is no datum shift anywhere in this
  codebase. Do not add GCJ-02 correction — it was deliberately removed.
- **No large language model in the product runtime.** Commute detection, mode
  inference and clustering are rule-based by design. AI writes the code; it is
  never a dependency of the code.

---

## 3. Language policy

| Scope | Language |
|---|---|
| All code and everything shipped with it — `.py` `.ts` `.tsx` `.sql` `.toml` `.json` `.env*` `.gitignore`, identifiers, comments, log lines, error messages | **English** |
| Rule and process files — this file, `ARCHITECTURE.md`, tool adapters, hooks | **English** |
| `docs/**` — design documents, working notes, Change Requests | **Chinese** |
| `README.md`, `SETUP.md` — the two files a newcomer reads first | **English + Chinese** |
| User-facing UI copy | Chinese, and **only** in `frontend/src/i18n/` |

Two deliberate exceptions, both because the CJK text is *input data*, not prose:

- `backend/scripts/verify_env.py` — `CJK_HAYSTACK` / `CJK_NEEDLE` are the
  fixtures for the CJK search check.
- `frontend/src/i18n/zh.ts` — the single module holding display strings.
  Components reference English keys; no CJK literal appears in a component.

---

## 4. The design → CR → code loop

This is the core rule. Nothing about it is optional.

```
  design change                                  code change
  ─────────────                                  ───────────
  edit docs/design/**                            read the reviewed CR
  bump the version header                        write code
  append to docs/design/CHANGELOG.md             run lint + tests
        │                                              │
        ▼                                              ▼
  open CR (status: draft)  ──review──▶  reviewed  ──▶  append the result
  docs/working/change-requests/                        to the same CR
  CR-NNN-<slug>.md                                     (status: implemented)
                                                              │
                                    ◀─────── loop closed ─────┘
```

**Four rules that carry the whole thing:**

1. **A design change never comes with code.** Changing `docs/design/**` produces
   a Change Request, not an implementation. Do not "just also fix" the code in
   the same breath.
2. **Code is written only against a reviewed CR.** `status: draft` means the
   design has not been confirmed yet — do not start. No CR means there is
   nothing to implement.
3. **Design and code never share a commit.** A commit touching `docs/design/**`
   must not touch `backend/**`, `frontend/**`, `.env.example` or build config,
   and vice versa. They may sit on the same branch, in sequence. Enforced by
   `.githooks/pre-commit` (see §8).
4. **The CR is written back after the code lands.** A CR left at `reviewed`
   after the code shipped is an open loop, and the next person cannot tell what
   was actually built.

### When there is no design change

Bug fixes, refactors, dependency bumps and test additions that implement the
existing design as written need no CR. Commit them directly with a `fix:`,
`refactor:`, `test:` or `chore:` prefix.

The moment a fix requires a decision the design does not answer — that is a
design gap. Stop, record the question in the design set's `working/qa-log.md`,
and open a CR once it is answered.

---

## 5. Change Request format

**Location:** `docs/working/change-requests/CR-NNN-<slug>.md`
**Numbering:** zero-padded, monotonic, never reused. `CR-007-streaming-parser.md`
**Language:** field names English (so tools can parse them), content Chinese.

Copy `docs/working/change-requests/TEMPLATE.md` from the design set. The full
specification is below, so a CR can be written without it. Front matter:

```yaml
---
id: CR-007
title: <一句话说明这次要改什么>
status: draft            # draft → reviewed → implemented | rejected
opened: 2026-08-16
design_version: v2.3     # 依据的设计书版本
design_docs: [04-data-contract.md]   # 被改动/依据的设计文档
model: claude-opus-5 via Claude Code 2.0.14   # 见下方格式
---
```

The body has three sections, in this order:

| Section | Written when | Content |
|---|---|---|
| `## 1. 变更要求` | opening | What must change and why. The design delta, the constraint, the acceptance criteria. Enough that someone else could implement it. |
| `## 2. 评审` | before coding | Who confirmed it, what was rejected, open questions. Flip `status` to `reviewed` here. |
| `## 3. 变更结果` | after coding | **Brief.** Files touched, what was actually built, where it deviated from §1 and why. Flip `status` to `implemented`. |

Section 3 stays short — the diff is in git, the reasoning is in §1. Three to ten
lines is normal. Detail belongs here rather than in the commit message; the
commit only carries the CR id.

### Recording the model

`model:` names what produced the change, in the form `<model-id> via <tool>`:

```yaml
model: claude-opus-5 via Claude Code 2.0.14
model: gpt-5-codex via GitHub Copilot
model: kimi-k2 via Kimi CLI
model: deepseek-v3 via Cline 3.2
model: human                      # no AI involved
model: claude-opus-5 via Claude Code 2.0.14, human review   # mixed
```

If the model changes between opening the CR and implementing it, append the
second one in §3 rather than overwriting the front matter.

### Relationship to the design CHANGELOG

They are complementary, not redundant. Keep both:

| | `docs/design/CHANGELOG.md` | Change Requests |
|---|---|---|
| Records | What the **design** now says, per version | What the **code** was asked to do, per change |
| Granularity | One entry per design version | One file per change |
| Links back | — | `design_version` + `design_docs` |

---

## 6. Commit rules

**Format** — English, subject ≤ 20 words, no trailing period:

```
type(scope): summary [CR-NNN]
```

```
feat(import): stream large Google exports without loading them [CR-007]
fix(fence): reject export whose scope intersects a fence [CR-008]
docs(design): raise data contract to v2.4 [CR-007]
perf(tiles): add GiST index on track geometry
chore(deps): pin pillow to 11.0.1
```

`[CR-NNN]` is required whenever a CR exists, omitted otherwise. Commits are the
index; the narrative lives in the CR. Do not paste a change list into a commit
body — if it needs more than the subject line, it needs a CR.

| `type` | Use for |
|---|---|
| `feat` | New behaviour |
| `fix` | Wrong behaviour made right |
| `perf` | Same behaviour, faster |
| `refactor` | Same behaviour, different shape |
| `docs` | `docs/**`, `README.md`, this file, `ARCHITECTURE.md` |
| `test` | Tests only |
| `chore` | Dependencies, config, tooling, housekeeping |

| `scope` | Area |
|---|---|
| `import` `parse` `pipeline` | Ingestion, format parsers, derivation |
| `query` `tiles` `export` | Read paths, vector tiles, PNG and data export |
| `fence` `security` | Privacy fences, local-mode guards |
| `db` | Models, migrations, SQL |
| `ui` | Frontend |
| `design` | `docs/design/**` |
| `deps` `infra` | Dependencies, tooling, environment |

**Never commit** unless asked to. Never push to `main` directly, and never
commit `Sample/`, `data/` or `.env` — verify with `git status` before staging,
not after.

---

## 7. Coding standards

These describe what the code already does. Match the file you are editing.

### Both languages

- **Comments explain *why*, never *what*.** The code says what. A comment earns
  its place by recording a decision, a measurement, or a trap — `# Measured
  2.5x speedup (12ms -> 5ms) on a 4000x3000 image`, not `# resize the image`.
- **Every module opens with a docstring or block comment** stating its job in
  one line, then the non-obvious constraint it exists to satisfy. Read
  `backend/contrail/api/tiles.py` or `frontend/src/api/client.ts` for the bar.
- **No dead code, no commented-out code, no `TODO` without a CR id.**
- **Reserved-but-unimplemented endpoints return `501`** with the route present.
  They are not deleted — the cloud path depends on them existing.

### Python (backend)

- Python **3.12** exactly. Not 3.13, not 3.14 — `pycairo`, `pillow-heif` and
  `timezonefinder` have no wheels there.
- `from __future__ import annotations` at the top of every module.
- **Ruff** is the formatter and linter. Line length **100**, rules
  `E, F, I, UP, B, SIM`, target `py312`. Config in `backend/pyproject.toml`.
- Full type annotations on every public function. Modern syntax: `list[str]`,
  `X | None`, never `Optional[X]` or `typing.List`.
- `snake_case` functions and variables, `PascalCase` classes,
  `UPPER_SNAKE` module constants.
- Layering is one-directional: `api → pipeline → parsers → core`.
  `core/` imports no framework and no database. Never import upward.
- Async everywhere on the request path. **CPU-bound work goes to a
  `ProcessPoolExecutor`** — blocking the event loop silently kills progress
  reporting and job cancellation.
- Structured logging only: `log.info("event name", extra={"key": value})`.
  Never f-string a value into the message, never log a coordinate or a path.
- SQLAlchemy 2.0 style: `Mapped[...]` / `mapped_column()`, no legacy `Column`.

### TypeScript (frontend)

- **`strict: true`**, plus `noUnusedLocals`, `noUnusedParameters`,
  `noUncheckedIndexedAccess`. Do not weaken `tsconfig.json` to land a change.
- No `any`. An unavoidable one carries a comment naming the reason.
- `PascalCase` components and their files, `camelCase` hooks/functions/variables.
- One component per file. Types in `src/api/types.ts` mirror the backend
  Pydantic schemas — when a schema changes, both change in the same commit.
- Server state via **TanStack Query**; client state via **Zustand**. Do not add
  a third state mechanism, and do not keep server data in Zustand.
- Import `@deck.gl/*` submodules, **never the `deck.gl` umbrella package** — it
  pulls in the whole ArcGIS SDK (124 MB) and a telemetry package, which is
  unacceptable in a privacy product. Verify after any dependency change:
  ```bash
  cd frontend && npm ls @arcgis/core @vaadin/vaadin-usage-statistics   # both must be (empty)
  ```
- No CJK string literal outside `src/i18n/`.

### SQL and migrations

- Every schema change is an Alembic migration. Never edit an applied migration —
  add a new one.
- Migrations carry their PostGIS functions with them. The fence functions
  (`contrail_fence_remove`, `contrail_fence_blur`, `contrail_jitter_endpoints`)
  live in `0001_initial_schema.py`; without them the export path errors out
  deliberately rather than leaking.
- Spatial columns are `geography(...,4326)`. Index anything filtered by bbox.

### Tests

- `pytest` under `backend/tests/`, `asyncio_mode = auto`.
- **A run where `-m privacy` tests are skipped is not a passing run.** They need
  PostGIS with the fence functions installed.
- Every parser trap found in real data gets a regression test with a comment
  citing where it was observed.

---

## 8. Before you commit

```bash
cd backend  && ruff check contrail tests scripts && pytest
cd frontend && npx tsc -b --force
```

Both lint steps pass on a clean tree — keep them that way. `pytest` needs a
migrated PostGIS database; a run that skips `-m privacy` proves nothing.

Three checks are **not** gates yet, because the current tree does not pass them.
Do not repair them inside an unrelated commit — each needs its own `chore:`
commit. Details and counts in [ARCHITECTURE.md](ARCHITECTURE.md) §12.

- `ruff check .` — 2 errors, both in `alembic/env.py`. `contrail/`, `tests/`
  and `scripts/` are clean, which is why the gate above names them explicitly.
- `ruff format --check .` — 14 of 58 files predate any formatter run.
- `npm run lint` — eslint is declared in `package.json` but not installed and
  has no config, so the script fails outright.

Run `ruff format` on **the files you changed**, never on the whole tree. A
repo-wide reformat inside a feature commit destroys exactly the traceability
this process exists to produce.

Enable the shared hook once per clone. It rejects any commit that mixes
`docs/design/**` with code:

```bash
git config core.hooksPath .githooks
```

---

## 9. Tool adapters

`AGENTS.md` is the single source. Everything else points at it.

| Tool | How it loads these rules |
|---|---|
| **Claude Code** | Reads [`CLAUDE.md`](CLAUDE.md), which points here. |
| **GitHub Copilot** | Reads [`.github/copilot-instructions.md`](.github/copilot-instructions.md), which points here. |
| **Kimi CLI, Codex, Cursor, Gemini CLI** | Read `AGENTS.md` at the repository root natively. Nothing to configure. |
| **DeepSeek, or any tool with no rules-file convention** | Open the session with the bootstrap line below. If you drive it through Cline or Roo Code, add a `.clinerules` file containing the same line. |

Bootstrap line for tools that load nothing automatically:

```
Read AGENTS.md and ARCHITECTURE.md at the repository root before making any change, and follow AGENTS.md exactly.
```

**Do not fork the rules.** A tool-specific file that contains actual rules
instead of a pointer will drift, and two developers on two tools will produce
two different codebases. That is the failure this document exists to prevent.

---

## 10. Working with AI agents

- **Read before writing.** The relevant design document first, then the CR, then
  the code. This repository's design documents are unusually specific; guessing
  contradicts them.
- **State assumptions out loud.** If the design does not answer a question,
  say so and record it in the design set's `working/qa-log.md` rather than
  picking silently.
- **Never invent a measurement.** Numbers in comments and documents here come
  from real runs against real data. If you did not measure it, do not write it.
- **Report honestly.** If tests fail, show the output. If part of the task was
  skipped, say which part and why.
- **Scope discipline.** Implement the CR. Adjacent problems you notice get
  reported, not fixed in passing — an unrelated fix in the same commit breaks
  the traceability this whole process is built on.

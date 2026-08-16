# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) before making any change to this repository, and
follow it exactly.** It holds the development rules for every contributor,
human or AI. [ARCHITECTURE.md](ARCHITECTURE.md) describes the system: modules,
pipeline, database, API index.

This file is a pointer, not a second copy of the rules. Do not add rules here —
they would drift from AGENTS.md and split the codebase across tools.

## If you read nothing else

A non-authoritative excerpt of [AGENTS.md](AGENTS.md) §2 and §4. When they
differ, AGENTS.md is right.

- `Sample/`, `data/` and `.env` hold real personal data. Never commit them,
  never quote coordinates from them.
- Never put a filesystem path in an HTTP request body. Photo directories are
  referenced by a one-shot `pick_token`.
- Never weaken a privacy-fence check to simplify a client.
- Design changes (`docs/design/**`) and code changes never share a commit.
  Code is written only against a Change Request whose `status: reviewed`.
- Commits: English, `type(scope): summary [CR-NNN]`, subject ≤ 20 words.
- Code and config are English. `docs/**` is Chinese. UI strings are zh/en/ja and
  live only in `frontend/src/i18n/`.

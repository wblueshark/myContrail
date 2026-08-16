# Contrail — Engineering Overview

What the system is made of, which module does what, and every API endpoint.

**This document is descriptive, not normative.** The authority is
the design set under `docs/design/` (Chinese). Where this file and the design
disagree, the design is right and this file is stale — fix it here. Rules for
changing anything: [AGENTS.md](AGENTS.md).

---

## 1. What this is

A **read-only aggregation layer** for personal location history. Contrail
collects nothing itself. The user brings their own exports — photos, Google
Timeline, sports-app tracks — and Contrail turns them into one queryable,
displayable, exportable trajectory.

| | |
|---|---|
| **Stage** | MVP. Single user, one machine, native install. Not a hosted service. |
| **Sources** | Photo EXIF · Google Timeline (4 parallel record streams) · GPX / TCX / FIT |
| **Core semantics** | Cluster into **Places** and **Tracks**, group into **Trips** by day. Cross-timezone movement is never split. |
| **Organisation** | One **Group** per Trip/Place, many **Tags**. |
| **Commute** | Rule-based detection at track level. Explicitly no LLM. |
| **Map** | Mapbox. Basemap and stored data are both WGS-84 — aligned by construction, no datum shift. |
| **Privacy** | Geofences over **all historical** home/work addresses, auto-suggested and user-confirmed. Export forces an explicit blur-or-remove choice. |
| **Output** | Interactive map, timeline, statistics, templated PNG export, full data dump. |

Deliberately not built in MVP: sharing, cloud mode, authentication, content
correction. Their routes and foreign keys exist and return `501`, so the cloud
path is an implementation rather than a migration.

---

## 2. Runtime topology

Two processes in local mode. Redis is installed and configured but carries no
import traffic — see §5.

```
   Browser  http://127.0.0.1:5173
      │
      │  Vite dev server, proxies /api → 127.0.0.1:8000
      ▼
   ┌──────────────────────────────────────────────────────┐
   │  FastAPI   uvicorn 127.0.0.1:8000                     │
   │                                                       │
   │  Host check → CORS → LocalGuard → RequestContext      │
   │       ↓                                               │
   │  api/  ──▶  pipeline/  ──▶  parsers/  ──▶  core/      │
   │       ↓                          ↓                    │
   │  tasks.py (in-process, SSE)   ProcessPoolExecutor     │
   │       ↓                          (CPU-bound work)     │
   │  picker.py — absolute paths never leave this process  │
   └───────┬──────────────────────────────┬────────────────┘
           │                              │
           ▼                              ▼
   PostgreSQL 18 + PostGIS 3.6     data/  (uploads, thumbs, exports,
   pg_trgm · pgcrypto                     basemap tile cache)

   Redis 8 — reserved for cloud mode (worker.py); unused by local imports
```

Middleware runs in reverse registration order: **Host → CORS → LocalGuard →
RequestContext → routes**. Host first, because a rebound hostname must be
rejected before anything else inspects the request. CORS next, so a preflight is
answered without needing the local token.

---

## 3. Repository layout

```
myContrail/
├── AGENTS.md                  development rules (English, this doc's companion)
├── ARCHITECTURE.md            this file (English)
├── README.md                  what Contrail is, tech stack, supported files (English + Chinese)
├── SETUP.md                   installation, first import, troubleshooting (English + Chinese)
├── assets/poster.png          the export sample shown in README
├── CLAUDE.md                  pointer → AGENTS.md
├── .github/copilot-instructions.md   pointer → AGENTS.md
├── .githooks/pre-commit       rejects commits mixing design and code
├── .env / .env.example        the ONLY env file; both frontend and backend read it
│
├── backend/
│   ├── contrail/              application package (see §4)
│   ├── alembic/               migrations; 0001 also creates the fence functions
│   ├── tests/                 pytest
│   ├── scripts/verify_env.py  23 capability checks, not just "is it installed"
│   ├── pyproject.toml         package metadata + dependency RANGES + ruff/pytest config
│   ├── requirements.txt       PINNED runtime versions (reproducible installs)
│   └── requirements-dev.txt   -r requirements.txt + pytest/ruff/mypy/hypothesis
│
├── frontend/                  React 18 + TypeScript + Vite 6
├── docs/                      NOT in this repo — design set, distributed separately (gitignored)
├── data/                      gitignored — uploads, thumbnails, exports, tile cache
└── Sample/                    gitignored — REAL personal data, never commit
```

> Dependencies are declared **twice on purpose**: `requirements.txt` pins exact
> versions for reproducibility, `pyproject.toml` declares ranges for upgrades.
> Change one, change the other in the same commit.

---

## 4. Backend modules

`backend/contrail/`. Layering is one-directional: **`api → pipeline → parsers →
core`**. `core/` imports no framework and no database.

### Top level

| Module | Responsibility |
|---|---|
| `main.py` | App factory, middleware stack, lifespan, `UnknownFormatError` → `422` handler |
| `config.py` | Pydantic settings from the root `.env`, clustering parameters, capability declaration per mode |
| `db.py` | Async engine and session management |
| `models.py` | SQLAlchemy 2.0 ORM, mirroring the DDL in design doc 05 §4 |
| `schemas.py` | Pydantic request/response models. Import-related schemas **forbid unknown fields** so a path cannot slip in |
| `security.py` | The four local-mode guards + `reject_path_fields()` |
| `picker.py` | OS-native directory picker and the one-shot `pick_token` registry. **Absolute paths live here and nowhere else** |
| `bootstrap.py` | First-run: the single local user and the default groups |
| `tasks.py` | In-process task manager with SSE progress and cancellation |
| `worker.py` | ARQ worker entry point — cloud mode only |
| `storage.py` | Object storage behind full URI keys (`fs://thumbs/ab/cd.webp`), so an S3 move rewrites no rows |
| `imaging.py` | Thumbnail generation. Always uses `Image.draft()` for DCT-scaled JPEG decode — measured 12ms → 5ms on 4000×3000 |
| `geocode.py` | Reverse geocoding via Mapbox, cached in `geocode_cache` |
| `logging_config.py` | Structured JSON logging |

### `core/` — pure helpers, no framework, no database

| Module | Responsibility |
|---|---|
| `geo.py` | Geodesy. Everything is WGS-84; no datum shift exists anywhere |
| `timezones.py` | Timezone from coordinates. Required, not optional — `timelinePath` records carry UTC-only timestamps |

### `parsers/` — one file per format family

| Module | Responsibility |
|---|---|
| `base.py` | The parser contract: `RawPointDTO`, `PlaceHint`, `TrackHint`, `SkipNote`, `UnknownFormatError` |
| `registry.py` | Format sniffing. An unrecognised file is **reported with a sample, never silently skipped** |
| `google_timeline.py` | On-device timeline export (2024-11 onwards). Dispatches **per record** across the 4 parallel streams |
| `google_legacy.py` | Legacy Takeout: `Records.json` and Semantic Location History |
| `tracks.py` | GPX / TCX / FIT. FIT carries semicircles and the Garmin epoch (1989-12-31) |
| `photo.py` | EXIF extraction — read-only, one pass |

> **The load-bearing fact about Google exports:** one file contains four
> concurrent record streams (`visit`, `activity`, `timelinePath`,
> `timelineMemory`) coexisting across 13 years. `visit` alone supplies stays for
> ~67% of the timeline, so stay-clustering only runs on the remainder. 91% of
> `activity` records fuse with `timelinePath` to yield travel mode *and* real
> route together.

### `pipeline/` — raw points → Places, Tracks, Trips, Anchors

| Module | Responsibility |
|---|---|
| `importer.py` | Orchestration. Dispatches CPU-bound work to a `ProcessPoolExecutor` |
| `types.py` | Intermediate structures shared between stages |
| `dedup.py` | Three-layer deduplication, coarse to fine |
| `fusion.py` | Fuses the four Google streams into complete Tracks and Places |
| `clustering.py` | Stay-point clustering by roaming distance over time |
| `trips.py` | Day-Trip generation. Cross-timezone movement stays whole |
| `modes.py` | Travel-mode inference — rule-based |
| `commute.py` | Commute detection at track level — rule-based |
| `anchors.py` | Place anchors: merging repeated visits to one location |
| `photos.py` | Photo location inference and association with Trip Places |
| `derive.py` | Recomputes the derived layer over a time window (`POST /recluster`) |
| `refresh.py` | Post-import passes: anchors, commute, fence suggestions, geocoding |

> A Trip's Place and a Photo's Place mean different things. They are
> **associated, never merged**.

### `render/` — server-side PNG export

| Module | Responsibility |
|---|---|
| `basemap.py` | Basemap tile fetch, on-disk cache, stitch |
| `png.py` | Composition: fetch geometry **through the fences**, draw, lay out the template |

> Pillow does layout and compositing; **cairo draws the vectors**.
> `ImageDraw.line()` has no antialiasing and produces stair-stepped edges.

### `api/` — everything under `/api/v1`

| Module | Routes |
|---|---|
| `system.py` | Capabilities, health, auth stubs |
| `imports.py` | Directory picking, prescan, upload, import tasks, undo |
| `query.py` | Trips, places, tracks, photos, search, stats, anchors |
| `tiles.py` | Vector tiles — the load-bearing piece of the rendering architecture |
| `organize.py` | Groups, tags, bulk assignment |
| `commute.py` | OD pairs, affected trips, bulk actions, recompute |
| `settings.py` | Settings, geofence CRUD, suggestions, recluster |
| `exports.py` | Fence check, preview, PNG export, full data dump |
| `corrections.py` | Reserved, deliberately `501` |

---

## 5. Import path

```
POST /fs/pick          native picker → pick_token (no path in the response)
       ↓
POST /sources/prescan  file count, GPS ratio, time span, format sniff
       ↓
POST /imports          202 + task_id
       ↓
GET  /imports/{id}/events        SSE progress, absolute counts (never a fabricated %)
       │
       ├─ parse    → RawPoint          streaming; ijson / lxml iterparse
       ├─ dedup    → three layers
       ├─ fuse     → Google's 4 streams
       ├─ cluster  → Place / Track
       ├─ trips    → day Trips
       ├─ modes    → travel mode
       └─ refresh  → anchors, commute, fence suggestions, geocoding
```

**Why imports run in-process rather than in the ARQ worker:** a photo import
needs the absolute directory path, and that path must not leave the API process.
Handing it to a worker would serialise it through Redis — exactly what the
`pick_token` design prevents. Local mode is single-user, so one process suffices.
`worker.py` stays for cloud mode, where the input is uploaded bytes behind a
storage key and no local path exists.

**ARQ orchestrates only.** Import work is CPU-bound (EXIF parsing, JPEG decode,
clustering, geometry simplification). Running it on an event loop blocks it, and
progress reporting and cancellation then stop working with no error raised.

---

## 6. Database schema

PostgreSQL 18 + PostGIS 3.6. Required extensions — all three, no substitutes:

| Extension | Purpose | Without it |
|---|---|---|
| `postgis` | Spatial index, `ST_AsMVT`, **fence clipping** | Nothing works |
| `pg_trgm` | CJK place-name search | "京都" fails to match "京都市" |
| `pgcrypto` | `gen_random_uuid()` | Table creation fails |

18 tables in `models.py`:

| Group | Tables |
|---|---|
| Identity | `app_user` |
| Ingestion | `source_file`, `raw_point`, `import_task` |
| Derived | `place`, `track`, `trip`, `place_anchor` |
| Media | `photo`, `photo_source` |
| Organisation | `group`, `tag`, `trip_tag`, `place_tag` |
| Features | `commute_od`, `geofence`, `geocode_cache`, `export_task` |

Every table carries `user_id`, even though MVP has exactly one user. The FKs and
routes are the reason cloud mode is an implementation and not a migration.

Spatial columns are `geography(..., 4326)`. Migration `0001_initial_schema.py`
also installs the fence functions — `contrail_fence_remove`,
`contrail_fence_blur`, `contrail_jitter_endpoints`. **Without them the export
endpoints error out.** That is intentional: when fencing cannot run, exporting
nothing is the correct outcome.

---

## 7. API index

63 endpoints, all under `/api/v1`. Interactive docs at
<http://127.0.0.1:8000/docs> while the backend is running. Semantics — query
parameters, error codes, payload shapes — are specified in
`docs/design/05-architecture.md` §5.

Regenerate this list from the routes:

```bash
grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/contrail/api/*.py
```

### System — `system.py`

| Method | Path | Notes |
|---|---|---|
| GET | `/capabilities` | Current mode and available features |
| GET | `/health` | Returns PostGIS version |
| GET | `/auth/me` | Fixed local identity |
| POST | `/auth/register` · `/auth/login` · `/auth/logout` | `501` — reserved |

### Import — `imports.py`

| Method | Path | Notes |
|---|---|---|
| POST | `/fs/pick` | Opens the native picker. → `{pick_token, display_name, file_count}`; `204` on cancel. **No absolute path in the response** |
| POST | `/sources/prescan` | `{pick_token}` or an upload probe. **Rejects any `path` field** |
| POST | `/sources/upload` | Chunked upload (`Content-Range`) → `upload_id` |
| POST | `/imports` | `202 {task_id}`. Photo sources pass a `pick_token`, never a path |
| GET | `/imports` · `/imports/{id}` | Task list / status |
| GET | `/imports/{id}/events` | **SSE** progress stream |
| DELETE | `/imports/{id}` | Cancel |
| GET | `/sources` | Imported files |
| DELETE | `/sources/{id}` | Undo an import, cascading to derived data |

### Query — `query.py`

| Method | Path | Notes |
|---|---|---|
| GET | `/trips` | `?from&to&bbox&mode&source&group&tag&commute&q&limit&cursor` |
| GET | `/trips/{id}` | Detail |
| GET | `/places` · `/tracks` | `?bbox&radius&center&from&to&group&tag&q` |
| GET | `/photos` | `?trip_id&place_id&bbox&from&to` |
| GET | `/photos/{id}/thumb` · `/photos/{id}/micro` | 512px · 64px map atlas |
| GET | `/anchors` | Place anchors with home/work inference |
| GET | `/search` | Place names (`pg_trgm` + `ILIKE`) and trip titles |
| GET | `/stats` | `?from&to&bbox&group&tag` |

> `GET /photos/{id}/original` **does not exist.** The original directory is never
> revisited after import and the product does not hold originals.

### Tiles — `tiles.py`

| Method | Path | Notes |
|---|---|---|
| GET | `/tiles/tracks/{z}/{x}/{y}.mvt` | `?from&to&mode&source&crs` |
| GET | `/tiles/places/{z}/{x}/{y}.mvt` | |
| GET | `/tiles/photos/{z}/{x}/{y}.mvt` | |

### Organise — `organize.py`

| Method | Path | Notes |
|---|---|---|
| GET · POST | `/groups` | `system_commute` cannot be deleted |
| PATCH · DELETE | `/groups/{id}` | |
| GET · POST | `/tags` | |
| PATCH · DELETE | `/tags/{id}` | |
| PATCH | `/trips/{id}` | **Metadata only**: `{title?, group_id?, tag_ids?}` |
| POST | `/trips/bulk-assign` · `/places/bulk-assign` | `{ids, group_id?, add_tags?, remove_tags?}` |

### Commute — `commute.py`

| Method | Path | Notes |
|---|---|---|
| GET | `/commute/ods` | OD pairs with evidence: counts, time bands, sample dates, distance |
| GET | `/commute/trips` | `?class=pure\|mixed` |
| POST | `/commute/trips/actions` | `{trip_ids, action: collapse\|to_normal\|delete}`. `delete` accepts `pure` only, else `422` |
| POST | `/commute/recompute` | Rerun with new parameters |

### Settings — `settings.py`

| Method | Path | Notes |
|---|---|---|
| GET · PUT | `/settings` | Clustering parameters, default timezone, geocoding toggle, basemap |
| GET | `/geofences` · `/geofences/suggestions` | Suggestions come in three confidence tiers |
| POST | `/geofences` · PATCH · DELETE `/geofences/{id}` | |
| POST | `/recluster` | Recompute derived layer; `is_auto=false` Trips are untouched |

### Export — `exports.py`

| Method | Path | Notes |
|---|---|---|
| POST | `/exports/fence-check` | **Must be called first.** Returns intersecting fences and affected counts |
| POST | `/exports/preview` | Low-res preview, 400×720, < 1s. Full render takes 3–8s |
| POST | `/exports` | `202 {task_id}`. **`422` if the scope intersects a fence and `fence_actions` is absent** |
| GET | `/exports/data` | Full dump: GeoJSON + GPX + thumbnail zip. Uncropped by default — it is the user's own data |
| GET | `/exports/{id}` · `/exports/{id}/file` | Status · download |

> Route order matters: `/exports/data` is declared **before** `/exports/{id}`,
> or `data` is captured as an id.
>
> `fence_actions` is enforced server-side. A client dialog can be bypassed; a
> `422` cannot. This is where "a fence leak is the only unacceptable bug" is
> actually enforced.

### Corrections — `corrections.py` — all `501`, reserved

`PUT /trips/{id}/content` · `PUT /trips/{id}/segments/{sid}` · `PUT /places/{id}`
· `POST /trips/{id}/split` · `POST /trips/merge`

---

## 8. Frontend

React 18 · TypeScript 5.7 (`strict`) · Vite 6 · Mapbox GL + deck.gl · TanStack
Query (server state) · Zustand (client state).

```
frontend/src/
├── main.tsx · App.tsx        entry, routing, token gate
├── api/
│   ├── client.ts             HTTP client — sets both mandatory headers
│   ├── types.ts              mirrors the backend Pydantic schemas
│   └── hooks.ts              TanStack Query hooks
├── components/
│   ├── MapCanvas.tsx         Mapbox + deck.gl, MVT layers
│   ├── TimelineSlider.tsx · FilterPanel.tsx
│   ├── DetailDrawer.tsx · ExportPanel.tsx
├── pages/                    Map · Timeline · Trips · TripDetail · Sources
│                             Groups · Commute · Settings
├── store/appStore.ts         Zustand
└── i18n/zh.ts                the ONLY file containing CJK display strings
```

Two conventions that are easy to break and expensive to fix:

- **Import `@deck.gl/*` submodules, never the `deck.gl` umbrella.** The umbrella
  pulls in the entire ArcGIS SDK (124 MB) plus a telemetry package.
  `npm ls @arcgis/core @vaadin/vaadin-usage-statistics` must print `(empty)`.
- **`vite.config.ts` sets `envDir` to the repository root.** There is one `.env`
  for the whole project. Only `VITE_`-prefixed keys reach the bundle, so
  `DATABASE_URL` and the local token stay out of it.

The dev server proxies `/api` to `127.0.0.1:8000` with `changeOrigin: false`, so
the browser origin stays on the CORS allowlist and the Host header stays a
loopback name. **The backend port must be 8000** — the proxy target is fixed.

---

## 9. Configuration

One `.env` at the repository root, read by both sides. Template: `.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `CONTRAIL_MODE` | `local` | `local` \| `cloud` |
| `CONTRAIL_ENABLE_AUTH` | `false` | Reserved |
| `CONTRAIL_STORAGE_BACKEND` | `fs` | `fs` \| `s3` |
| `DATABASE_URL` | — | `postgresql+psycopg://user:pw@localhost:5432/mycontrail` |
| `REDIS_URL` | `redis://localhost:6379/0` | Cloud mode only |
| `CONTRAIL_DATA_DIR` | `<repo>/data` | Uploads, thumbnails, exports, tile cache |
| `MAPBOX_TOKEN` | — | Server-side: basemap tiles for PNG export, geocoding |
| `VITE_MAPBOX_TOKEN` | — | Client-side. Same token is fine |
| `CONTRAIL_GEOCODING_ENABLED` | `true` | |
| `CONTRAIL_LOCAL_TOKEN` | — | Falls back to `~/.contrail/token`, generated on first start |
| `CONTRAIL_ALLOWED_ORIGINS` | loopback | Strict allowlist, never `*` |
| `CONTRAIL_ALLOWED_HOSTS` | loopback | Anything else → `421` |

Clustering parameters are code defaults in `config.py`, overridable at runtime
through `PUT /settings`: `cluster_radius_m` 150 · `cluster_min_dwell_s` 900 ·
`cluster_gap_s` 3600 · `cluster_max_inferred_stay_s` 86400 · `accuracy_max_m`
500 · `photo_infer_tolerance_s` 1800.

> `CONTRAIL_ALLOWED_SCAN_ROOTS` was **removed in design v2.3**. If it is still in
> your `.env`, delete the line — `verify_env.py` fails on it.

---

## 10. Security model

"It binds 127.0.0.1, so it is safe" is false. Four guards, each blocking a
different real attack:

| Guard | Blocks |
|---|---|
| **Host header check** | DNS rebinding — a hostile page rebinds its own hostname to 127.0.0.1, escapes same-origin, and reads the entire history |
| **Strict CORS allowlist** | Which origins the browser will hand responses to. Never `*`: with no authentication there is no credential to withhold |
| **`X-Contrail-Client`** | CSRF. A hostile page could otherwise issue `DELETE /api/v1/sources/{id}`. A simple cross-origin form or image request cannot set a custom header |
| **`X-Contrail-Token`** | Other processes on the same machine calling the API. From `~/.contrail/token` |

**Path traversal is handled structurally, not by validation.** Absolute paths
never appear in any request: the picker keeps them in a process-local one-shot
table and hands out a `pick_token`. `reject_path_fields()` turns any request
carrying `path`/`directory`/`root`/`scan_path`/`abs_path` into a `400`, and the
import schemas set `extra="forbid"`. There is no persisted scan root anywhere, so
"never re-reads your photo directory" is a structural guarantee rather than a
promise.

**Encryption:** application-level AES-256-GCM on retained originals and
thumbnails is a *cloud-mode* requirement, where a bucket may be misconfigured.
The local threat model is a stolen laptop, which FileVault already covers. The
cipher is pluggable and currently a pass-through. Coordinate columns are
deliberately not encrypted at the application layer — PostGIS must index and
clip them.

---

## 11. Build, run, test

Full first-time setup, including Homebrew dependencies and database creation:
[SETUP.md](SETUP.md). Daily commands:

```bash
# terminal 1 — backend (port MUST be 8000)
conda activate py312
uvicorn contrail.main:app --host 127.0.0.1 --port 8000 --app-dir backend --reload

# terminal 2 — frontend
cd frontend && npm run dev            # http://127.0.0.1:5173
```

```bash
python backend/scripts/verify_env.py               # 23 capability checks
alembic -c backend/alembic.ini upgrade head        # migrate

cd backend  && ruff check contrail tests scripts && pytest
cd frontend && npx tsc -b --force && npm run build
```

Those two check lines pass on a clean tree. `ruff check .` (including
`alembic/`), `ruff format --check .` and `npm run lint` do not — see §12.

`verify_env.py` does not check whether packages import. It verifies the
capabilities the design depends on actually hold: metric correctness of fence
buffers, MVT generation, CJK search, whether the GiST index is really used,
DCT-scaled JPEG decode, antialiasing, timezone reverse lookup.

Test suites in `backend/tests/`: `test_parsers.py` · `test_clustering.py` ·
`test_trips_and_modes.py` · `test_privacy_fence.py` · `test_api_contract.py`.
**A run where `-m privacy` tests are skipped is not a passing run** — they
require PostGIS with the fence functions installed.

---

## 12. Known gaps

Recorded rather than hidden. Fixing any of these needs a Change Request first
(see [AGENTS.md](AGENTS.md) §4).

| Gap | Detail |
|---|---|
| **Frontend lint is broken** | `package.json` declares `"lint": "eslint . --ext ts,tsx"`, but eslint is not in `devDependencies` and there is no config file. The script fails outright. Type checking via `npx tsc -b --force` passes clean |
| **`ruff format` never ran** | 14 of 58 Python files would be reformatted. Formatting is therefore not a gate; format only the files you touch |
| **`alembic/env.py` fails lint** | 2 errors (`I001`, `SIM103`). `contrail/`, `tests/` and `scripts/` pass, which is why the documented gate names those three explicitly |
| **mypy is unconfigured** | It is a dev dependency, but `pyproject.toml` has no `[tool.mypy]` section — strictness is undefined and it is not part of any check |
| **No frontend tests** | No test runner at all. The backend has pytest |
| **No CI** | Every check is manual and local |
| **Implementation is uncommitted** | ~8,000 lines across 85 untracked files. Distribution requires a baseline commit first |
| **No GPX / TCX / FIT samples** | The track parsers have no real-file verification. Google and photo paths were validated against 13 years of real data (49,654 records, 2013-09 → 2026-07) |
| **2 open design questions** | `Q-R3-15` (do historical fences apply across all time?) and `Q-R3-14` (adopt Google Places for names?) — `docs/working/qa-log.md` |

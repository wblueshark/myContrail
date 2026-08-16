# Setup · 安装手顺

Local single-user mode (MVP). You need **two terminal windows**: one for the
backend, one for the frontend.

本机单用户模式（MVP）。全程需要**两个终端窗口**：一个跑后端，一个跑前端。

> Already installed? Skip to [step 8](#8-start-the-backend--启动后端) and
> [step 9](#9-start-the-frontend--启动前端) — those two commands are the whole
> daily routine.
> 已经装好环境的话，日常启动只要[第 8 步](#8-start-the-backend--启动后端)和[第 9 步](#9-start-the-frontend--启动前端)两条命令，直接跳过去。

What Contrail is and what it does: **[README.md](README.md)**.
产品是什么、能做什么：**[README.md](README.md)**。

---

## Requirements · 环境要求

| Component · 组件 | Version · 版本 | Notes · 说明 |
|---|---|---|
| macOS | Apple Silicon / Intel | Photo import uses the OS-native folder picker, which only exists in a native install.<br>照片导入依赖系统原生目录选择器，**只在本机原生安装下成立**。 |
| PostgreSQL | 18 | with PostGIS 3.6 · 需配 PostGIS 3.6 |
| Redis | 8.x | Local imports do not go through it; reserved for cloud mode.<br>本机模式下导入不经过它，为 cloud mode 预留。 |
| Python | **3.12** | Not 3.14 — see [troubleshooting F](#f-pip-cannot-install-pycairo--pillow-heif--timezonefinder--pip-装不上-pycairo--pillow-heif--timezonefinder).<br>不能用 3.14，见[排错 F](#f-pip-cannot-install-pycairo--pillow-heif--timezonefinder--pip-装不上-pycairo--pillow-heif--timezonefinder)。 |
| Node | 20+ | tested on 24.18 · 实测 24.18 |

---

## 1. System dependencies · 系统依赖

```bash
brew install postgresql@18 postgis redis cairo libheif
brew services start postgresql@18
brew services start redis
```

`cairo` and `libheif` must come first: the former draws the antialiased routes in
exported images, the latter reads iPhone HEIC. Without them `pip install`
compiles from source on the spot and fails.

`cairo` 和 `libheif` 必须先装：前者是导出图抗锯齿绘制的依赖，后者是读 iPhone HEIC 的依赖。缺了它们 `pip install` 会当场编译并失败。

Confirm both services are up · 确认两个服务都起来了：

```bash
brew services list | grep -E "postgresql|redis"
# postgresql@18 started
# redis         started
```

> Redis won't start? → [troubleshooting E](#e-redis-wont-start-redisbloomso-fails-to-load--redis-起不来报-redisbloomso-加载失败).
> Redis 起不来 → [排错 E](#e-redis-wont-start-redisbloomso-fails-to-load--redis-起不来报-redisbloomso-加载失败)。

## 2. Create the database · 创建数据库

```bash
createdb mycontrail
psql -d mycontrail -c "CREATE USER appresu WITH PASSWORD 'your-own-password';"
psql -d mycontrail -c "ALTER DATABASE mycontrail OWNER TO appresu;"
psql -U appresu -d mycontrail -c "CREATE EXTENSION postgis;"
psql -U appresu -d mycontrail -c "CREATE EXTENSION pg_trgm;"
psql -U appresu -d mycontrail -c "CREATE EXTENSION pgcrypto;"
```

All three extensions are required, each for a specific reason:
三个扩展都是必需的，各有明确用途：

| Extension · 扩展 | Purpose · 用途 | Without it · 缺了会怎样 |
|---|---|---|
| `postgis` | Spatial index, `ST_AsMVT` tiles, **privacy-fence clipping**<br>空间索引、`ST_AsMVT` 瓦片、**隐私围栏裁剪** | Nothing works at all · 整个产品跑不起来 |
| `pg_trgm` | CJK place-name search · 中日文地名搜索 | "京都" fails to match "京都市" · 搜「京都」匹配不到「京都市」 |
| `pgcrypto` | `gen_random_uuid()` | Table creation fails · 建表就失败 |

## 3. Backend Python environment · 后端 Python 环境

```bash
conda create -n py312 python=3.12     # skip if you already have it · 已有就跳过
conda activate py312
pip install -r backend/requirements-dev.txt
```

`requirements-dev.txt` starts with `-r requirements.txt`, so installing that one
file is enough (it includes pytest / ruff / mypy). To run without developing, use
`backend/requirements.txt`.

`requirements-dev.txt` 首行 `-r requirements.txt`，装它一个就够（含 pytest / ruff / mypy）。只跑不开发的话用 `backend/requirements.txt`。

## 4. Frontend dependencies · 前端依赖

```bash
cd frontend
npm install
cd ..
```

About 206 MB. Check the dependency tree afterwards · 装完约 206 MB，建议查一次依赖树：

```bash
cd frontend && npm ls @arcgis/core @vaadin/vaadin-usage-statistics
# both should print (empty) · 两个都应该是 (empty)
```

The `deck.gl` umbrella package drags in the entire ArcGIS SDK (124 MB) and a
telemetry package — unacceptable in a product whose whole premise is privacy.
`package.json` already uses the specific submodules; this command guards against
another dependency pulling the umbrella back in.

`deck.gl` 伞包会拖进整个 ArcGIS SDK（124 MB）和一个遥测包 —— 在一个以隐私为立身之本的产品里不能接受。`package.json` 里已经改用具体子模块，这条命令是防它被别的依赖重新拖回来。

## 5. Configure `.env` · 配置 `.env`

```bash
cp .env.example .env
```

Edit it and change **at least these two** · 编辑 `.env`，**至少改这两处**：

```bash
# the password you set in step 2 · 第 2 步设的密码
DATABASE_URL=postgresql+psycopg://appresu:your-password@localhost:5432/mycontrail

# create a public token (pk.*) at https://account.mapbox.com/access-tokens/
# adding a URL restriction is recommended. The same token works for both.
# 建一个 public token（pk. 开头），建议加 URL 限制。两处可以填同一个。
VITE_MAPBOX_TOKEN=pk.xxxxxxxx
MAPBOX_TOKEN=pk.xxxxxxxx
```

If your `.env` was carried over from an older version, **delete the
`CONTRAIL_ALLOWED_SCAN_ROOTS` line** — v2.3 removed the scan-root allowlist. The
setting is now ignored, and the guard did not disappear so much as move: requests
no longer carry a path field at all (see [step 11](#11-import-your-first-data--导入第一份数据)).
Leaving the line in place is only misleading.

如果你的 `.env` 是从旧版本沿用下来的，**删掉 `CONTRAIL_ALLOWED_SCAN_ROOTS` 那一行** —— v2.3 已经取消了扫描目录白名单，这个配置项现在会被忽略（护栏没有消失，而是换成了「请求里根本没有路径字段」，见[第 11 步](#11-import-your-first-data--导入第一份数据)）。留着它只会误导。

> **The whole project has exactly one `.env`, at the repository root.** Both
> frontend and backend read it. The frontend only ever sees `VITE_`-prefixed
> keys, so the database password and the local token never reach the bundle.
>
> **整个项目只有仓库根目录这一份 `.env`**，前端和后端都从这里读。前端只能看到 `VITE_` 开头的变量，数据库密码和本机 token 不会进前端产物。

> Without a Mapbox token it still starts: the basemap is blank, but import,
> clustering, queries, fences and data export all work normally.
>
> 没有 Mapbox token 也能启动：底图不显示，但导入、聚类、查询、围栏、数据导出全部照常工作。

## 6. Verify the environment · 环境自检

```bash
python backend/scripts/verify_env.py
```

This script does not merely check that packages import. It verifies that the
capabilities the design depends on actually hold: metric correctness of fence
buffers, MVT generation, CJK search, whether the GiST index is really being used,
DCT-scaled JPEG decoding, antialiasing, and timezone reverse lookup.

这个脚本不只检查「包装上了没」，而是逐项验证**设计所依赖的能力是否真的成立** —— 围栏 buffer 的米制正确性、MVT、CJK 搜索、GiST 索引是否真的被用上、JPEG 的 DCT 缩放解码、抗锯齿、时区反查。

Expect **23/23 passed**. Failures are listed separately at the end, each with an
actionable next step. The two common ones: the Mapbox token is unset (back to
step 5), and `native directory picker` reporting
`CONTRAIL_ALLOWED_SCAN_ROOTS is set` (delete that line from `.env`).

预期 **23/23 通过**。有失败项时脚本会在末尾单独列出来，每条都带可执行的下一步。常见的两条：`Mapbox token` 没填（回第 5 步），`native directory picker` 报 `CONTRAIL_ALLOWED_SCAN_ROOTS is set`（删掉 `.env` 里那一行）。

## 7. Create the tables · 建表

```bash
alembic -c backend/alembic.ini upgrade head
```

Expected output · 预期输出：

```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, Initial schema: ...
```

Confirm · 确认一下：

```bash
alembic -c backend/alembic.ini current
# 0001 (head)
```

This step also creates the PostGIS privacy-fence functions
(`contrail_fence_remove` / `contrail_fence_blur` / `contrail_jitter_endpoints`).
**Without them the export endpoints error out** — deliberately: when fencing
cannot run, exporting nothing is the correct outcome.

这一步同时创建了隐私围栏的 PostGIS 函数（`contrail_fence_remove` / `contrail_fence_blur` / `contrail_jitter_endpoints`）。**没有它们，导出接口会直接报错**，这是有意的 —— 围栏失效时宁可导不出来。

## 8. Start the backend · 启动后端

**Terminal 1 · 终端 1**：

```bash
conda activate py312
uvicorn contrail.main:app --host 127.0.0.1 --port 8000 --app-dir backend --reload
```

> The port **must be 8000** — the frontend dev server proxies to a hard-coded
> `127.0.0.1:8000`.
> 端口必须是 **8000**：前端 dev server 的代理写死指向 `127.0.0.1:8000`。

Verify · 验证：

```bash
curl -s http://127.0.0.1:8000/api/v1/health
# {"status":"ok","postgis":"3.6.4"}
```

API docs at <http://127.0.0.1:8000/docs>. · API 文档在 <http://127.0.0.1:8000/docs>。

## 9. Start the frontend · 启动前端

**Terminal 2 · 终端 2**：

```bash
cd frontend
npm run dev
```

Open <http://127.0.0.1:5173>. · 浏览器打开 <http://127.0.0.1:5173>。

> You must use `127.0.0.1` or `localhost`. The backend has a Host-header
> middleware that rejects anything else with `421` — this blocks **DNS
> rebinding**: you visit some malicious page, its JavaScript rebinds its own
> domain to 127.0.0.1, and it can then bypass the same-origin policy and read
> your entire location history.
>
> 必须用 `127.0.0.1` 或 `localhost` 访问。后端有 Host 头校验中间件，别的主机名一律 421 —— 这是在挡 **DNS rebinding**：你浏览任意一个恶意网页，该页的 JS 把自己的域名重绑到 127.0.0.1，就能绕过同源策略读走你的全部位置历史。

## 10. First connection: paste the local token · 首次连接：粘贴本机令牌

The page asks for a token first. Get it · 页面会先要一个令牌，取出来：

```bash
cat ~/.contrail/token
```

It was generated the first time the backend started. Paste it, click Connect, and
the browser remembers it.

后端首次启动时自动生成的。粘进去点「连接」，之后浏览器会记住。

> This is not a login. It blocks **other processes on your machine** from calling
> the API. "It binds 127.0.0.1, so it is safe" is false — local mode has four
> guards in total: the local token, the Host header check, the CORS allowlist,
> and a custom `X-Contrail-Client` header required on writes.
>
> 这不是登录。它挡的是**同机其他进程直接调 API**。「绑定了 127.0.0.1 就安全」并不成立 —— 本机模式一共四道护栏：本机令牌、Host 头校验、CORS 白名单、写操作要求自定义头 `X-Contrail-Client`。

## 11. Import your first data · 导入第一份数据

Go to **📥 数据源** (Sources) · 进 **📥 数据源**：

| To import · 想导入 | How · 怎么做 |
|---|---|
| Google Timeline<br>(`location-history.json` / `Timeline.json`) | "导入轨迹文件" on the right. The format is sniffed and echoed back for confirmation before the import starts.<br>右侧「导入轨迹文件」选文件。上传后会先做格式嗅探并回显识别结果，确认后开始。 |
| Sports tracks (GPX / TCX / FIT)<br>运动轨迹 | Same as above · 同上 |
| Photos · 照片 | "选择照片目录" on the left → your OS folder picker opens.<br>左侧「选择照片目录」→ 弹出系统目录选择框。 |

**The photo directory path never enters an HTTP request.** The backend opens
Finder, stores the absolute path in a one-shot in-memory table, and hands the
frontend only a `pick_token`. Path traversal is therefore structurally
impossible — there is no path field in the request to poison. By the same token
no scan root is persisted anywhere, which makes "the original folder is never
read again after import" a structural guarantee rather than a promise.

**照片目录的路径全程不进 HTTP 请求**：后端弹出 Finder，把绝对路径存进进程内存的一次性表，只把 `pick_token` 给前端。所以路径遍历在结构上不可能 —— 请求里根本没有可以被污染的路径字段。同样地，系统里不保存任何扫描根目录，「导入后永不再访问原目录」因此是结构保证而不是承诺。

Progress is reported live over SSE. When the total is unknown it shows an
**absolute count**, not a fabricated percentage.

导入过程通过 SSE 实时上报进度。总量未知时显示的是**绝对条数**而不是编造的百分比。

> ⚠️ macOS may prompt for privacy authorisation (TCC) the first time it reads
> `~/Pictures` / `~/Desktop` / `~/Documents`. If the scan finds 0 files, add your
> terminal (or IDE) under System Settings → Privacy & Security → Full Disk Access.
>
> ⚠️ macOS 首次读 `~/Pictures` / `~/Desktop` / `~/Documents` 可能触发系统隐私授权（TCC）。如果扫描结果是 0 个文件，去「系统设置 → 隐私与安全性 → 完全磁盘访问权限」把终端（或你的 IDE）加进去。

## 12. After import: confirm the fences before looking at the map · 导入完成后：先确认隐私围栏，再看地图

Go to **⚙️ 设置 → 隐私围栏** (Settings → Privacy fences). Home and workplace
candidates have already been inferred from your data, in three confidence tiers:

进 **⚙️ 设置 → 隐私围栏**。系统已经从你的数据里推算出住址/公司候选，按可信度分成三档：

| Tier · 档位 | Meaning · 含义 |
|---|---|
| ✅ Confirmed by Google · Google 已确认 | `semanticType = Home / Work` |
| ⚠️ Inferred by Google · Google 推断的 | `Inferred Home / Inferred Work` |
| 📊 Inferred by us · 我们统计出来的 | Overnight / weekday dwell ratios · 夜间 / 工作日停留占比 |

**Confirm all three tiers separately — do not just click one.** In real data,
"Google's confirmed home" and "Google's inferred home" sat several hundred metres
apart and were genuinely different places. Confirming only one leaves the other
completely unprotected.

**三档要分别确认，不要只点一个。** 实测「Google 确认的家」与「Google 推断的家」相距数百米，是不同的地方 —— 只确认其中一处，另一处完全没有被保护。

The inference runs entirely offline. Your address is never sent to any third
party. 推算全程离线，不会把你的住址发给任何第三方。

---

## Daily start · 日常启动

```bash
# terminal 1 · 终端 1
conda activate py312 && uvicorn contrail.main:app --host 127.0.0.1 --port 8000 --app-dir backend --reload

# terminal 2 · 终端 2
cd frontend && npm run dev
```

<http://127.0.0.1:5173>

**To stop** · **停止**：`Ctrl+C` in each terminal. The database and Redis are brew
background services · 两个终端各按一次 `Ctrl+C`。数据库和 Redis 是 brew 后台服务，要停的话：

```bash
brew services stop postgresql@18
brew services stop redis
```

---

## Contributing · 参与开发

One extra step per clone. It enables the shared git hooks, which reject commits
that mix design documents with code, or that stage private data.

每个 clone 多做一步，启用共享的 git 钩子 —— 它会拒绝「设计与代码混在同一个 commit」以及误把私有数据加入暂存区的提交。

```bash
git config core.hooksPath .githooks
```

Read **[AGENTS.md](AGENTS.md)** before your first change. It holds the
development rules for every contributor, human or AI, and
**[ARCHITECTURE.md](ARCHITECTURE.md)** describes the system.

第一次改动前先读 **[AGENTS.md](AGENTS.md)** —— 面向全部开发者与 AI 工具的开发规则；系统构成见 **[ARCHITECTURE.md](ARCHITECTURE.md)**。

---

## Appendix · 附录

### A. The ARQ worker (not needed locally) · ARQ worker（本机模式不需要）

```bash
cd backend && arq contrail.worker.WorkerSettings
```

**Local imports do not go through it.** A photo import needs the absolute
directory path, and that path must stay inside the API process — handing it to a
worker would serialise it through Redis, exactly what the `pick_token` design
prevents. The worker is reserved for cloud mode, which works from storage keys
rather than paths.

**本机模式下导入不走它。** 照片导入需要目录绝对路径，而这个路径必须留在 API 进程内存里 —— 交给 worker 就等于经 Redis 序列化，正是 `pick_token` 设计要防的事情。worker 保留给 cloud mode（按 storage key 而非路径工作）。

### B. Running the tests · 跑测试

```bash
cd backend
pytest tests -q                        # all · 全部，预期 91 passed
pytest tests -q -m privacy             # privacy-fence regressions only · 只跑隐私围栏回归
ruff check contrail tests scripts      # expect All checks passed
```

**The privacy-fence regressions are a blocking check.** They verify that all
2 strategies × 3 layers = 6 combinations contain no coordinate inside a fence, and
they watch two traps that look like a pass while actually leaking: the buffer must
be metric (a degree-based conversion is only 384 m wide at Beijing's latitude),
and endpoints must be jittered (without it, three endpoints are enough to
trilaterate the centre).

**隐私围栏回归测试是 CI 的阻断项。** 它验证 2 种策略 × 3 个图层 = 6 个组合都不含围栏内坐标，另外还盯着两个「看起来通过了但其实在泄漏」的坑：buffer 必须是米制的（度数换算在北京纬度只有 384 m 宽），断点必须做扰动（不扰动的话三个断点就能三点定圆算出圆心）。

> ⚠️ These tests need a live PostGIS connection. **A run in which they were
> SKIPPED is not a passing run.**
> ⚠️ 这些测试需要连上 PostGIS。**它们 SKIP 掉的那次 CI 不算通过。**

### C. Full recomputation · 完整重算

After changing the clustering parameters, use **⚙️ 设置 → 用新参数重算**, or:
改了聚类参数之后，在 **⚙️ 设置 → 用新参数重算**，或者：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recluster \
  -H "X-Contrail-Token: $(cat ~/.contrail/token)" \
  -H "X-Contrail-Client: contrail-web"
```

Only the derived layer (places / tracks / trips) is affected; raw points are left
alone. 只影响派生层（地点 / 路途 / 行程），原始点不动。

### D. Export all your data · 导出你的全部数据

**⚙️ 设置 → 导出全部数据**, or directly · 或直接：

```bash
curl -O -J http://127.0.0.1:8000/api/v1/exports/data \
  -H "X-Contrail-Token: $(cat ~/.contrail/token)"
```

GeoJSON + GPX, packaged. **No fence clipping** — this is your own data. The
fences protect the channel that publishes outward.

GeoJSON + GPX 打包。**不做围栏裁剪** —— 这是你自己的数据，围栏保护的是「对外发布」的那条通道。

---

## Troubleshooting · 排错

### A. Blank frontend / no basemap · 前端一片空白 / 地图不显示

Basemap blank but the filter panel on the left renders fine → the Mapbox token is
wrong. Check `VITE_MAPBOX_TOKEN` in `.env`, and **restart `npm run dev`
afterwards** — Vite reads `.env` only at startup.

底图空白但左侧筛选面板正常 → Mapbox token 没配好。检查 `.env` 里的 `VITE_MAPBOX_TOKEN`，**改完必须重启 `npm run dev`**（Vite 只在启动时读 `.env`）。

### B. Frontend says it cannot reach the backend · 前端报「连接不上后端」

The backend is not running, or not on port 8000. The frontend proxy points at a
hard-coded `127.0.0.1:8000`.

后端没起，或没跑在 8000 端口。前端代理写死指向 `127.0.0.1:8000`。

### C. Every request returns 401 · 所有请求 401

Wrong token. Re-read it with `cat ~/.contrail/token`. Deleting that file and
restarting the backend generates a new one (the old one stops working
immediately).

令牌不对。`cat ~/.contrail/token` 重新取一次。删掉这个文件重启后端会重新生成一个（旧的随即失效）。

### D. Writes return 403, reads work · 写操作 403，读操作正常

The `X-Contrail-Client: contrail-web` header is missing. This is the CSRF guard:
with no authentication there is no credential to require, so a hostile page
issuing `DELETE /api/v1/sources/{id}` would otherwise always succeed. Add the
header yourself when calling write endpoints with curl.

缺 `X-Contrail-Client: contrail-web` 头。这是 CSRF 护栏：没有认证就意味着没有凭证可要求，恶意页面发一个 `DELETE /api/v1/sources/{id}` 就一定成功。用 curl 手动调写接口时要自己带上。

### E. Redis won't start, `redisbloom.so` fails to load · Redis 起不来，报 `redisbloom.so` 加载失败

A Homebrew packaging bug: `redis.conf` carries four `loadmodule ./modules/...`
lines, but the `.so` files do not exist. ARQ does not use those modules.

Homebrew 打包 bug：`redis.conf` 里有 4 行 `loadmodule ./modules/...`，但 `.so` 文件根本不存在。ARQ 用不到这些模块：

```bash
cp /opt/homebrew/etc/redis.conf /opt/homebrew/etc/redis.conf.bak
sed -i '' 's|^loadmodule \./modules/|# loadmodule ./modules/|' /opt/homebrew/etc/redis.conf
brew services restart redis
```

### F. pip cannot install pycairo / pillow-heif / timezonefinder · pip 装不上 pycairo / pillow-heif / timezonefinder

Two possible causes · 两个原因：

1. **Wrong Python version.** These three have no prebuilt wheels for 3.14, so pip
   compiles from source and fails. You must `conda activate py312`; confirm with
   `python -V` that it is 3.12.x.
   **Python 版本不对。** 这三个包在 3.14 上没有预编译 wheel，会现场编译并失败。必须 `conda activate py312`，`python -V` 确认是 3.12.x。
2. **System libraries missing.** Back to step 1: `brew install cairo libheif`.
   **系统库没装。** 回到第 1 步 `brew install cairo libheif`。

### G. `alembic: command not found`

The conda environment is not active. Run `conda activate py312`, or use
`python -m alembic -c backend/alembic.ini upgrade head`.

conda 环境没激活。`conda activate py312`，或者用 `python -m alembic -c backend/alembic.ini upgrade head`。

### H. The photo folder scan finds 0 files · 照片目录扫描出 0 个文件

macOS TCC authorisation. See the note at the end of
[step 11](#11-import-your-first-data--导入第一份数据).

macOS TCC 授权。见[第 11 步](#11-import-your-first-data--导入第一份数据)末尾的说明。

### I. Export returns 422, "the scope intersects a privacy fence" · 导出报 422，说「范围内有隐私围栏」

**This is correct behaviour, not a bug.** When the export scope intersects a
fence you must first choose blur or remove. The frontend shows a blocking dialog;
if you are calling it with curl, put `"fence_actions": "blur"` or `"remove"` in
the request body.

**这是正确行为，不是 bug。** 导出范围与围栏相交时必须先选「模糊」或「删除」。前端会弹阻断式对话框；用 curl 手动调的话，请求体里要带 `"fence_actions": "blur"` 或 `"remove"`。

This server-side 422 cannot be bypassed — a frontend dialog can be, a server
refusal cannot. A fence leak is the one unacceptable bug in this product.

服务端的这个 422 不能绕过 —— 前端对话框可以被绕过，服务端的拒绝不能。围栏泄漏是这个产品唯一不可接受的 bug。

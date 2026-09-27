# waytoagi-static-pages

把静态页挂到 `www.waytoagi.com` 的路径下，例如 `www.waytoagi.com/usecase-atlas/opus5-5/`。

```
外部仓库@SHA ─┐
sites/<name> ─┴─ mounts.yaml ──assemble──▶ dist/ ──EdgeOne Pages──▶ static-origin.waytoagi.com
                                                                          │ 每个前缀一条 L7 回源规则
                                                                          ▼
                                                     www.waytoagi.com/<前缀>/<页面>/
```

主站其他路径不受影响，仍然回源主站。设计与决策见 [docs/design.md](docs/design.md)，操作手册见 [docs/runbooks/](docs/runbooks/)。实施记录和规则快照只保存在维护者本地（`docs/internal/`，不提交）。

## 新增或更新一个页面

1. 编辑 `mounts.yaml`：
   - **外部仓库**：填 `repo`、`dir`，`ref` 必须是完整的 40 位 commit SHA；
   - **放在本仓库**：页面放进 `sites/<name>/`，然后写 `source: { inline: sites/<name> }`。
2. `path` 必须位于已登记的 `namespaces` 前缀下（例如 `/usecase-atlas/<name>/`）。新前缀见下文。
3. 提 PR。CI 会拉取源码组装 `dist/`，并做以下检查：凭证扫描、以 `/` 开头的绝对路径引用（挂到子路径后会失效）、在最终嵌套路径上的浏览器冒烟测试、和线上源站的差异对比。
4. 合并后 `deploy` workflow 自动执行：部署到 Pages（按部署 ID 确认生效）→ 逐文件校验源站 → 只清变更挂载的 www 缓存 → 验证正式地址和主站回归 → 发飞书记录。

页面要求：
- 目录里有 `index.html`；
- 资源用**相对路径**引用；
- 点文件不会发布；
- 可以在 `exclude` 里写额外要排除的文件。

**回滚**：`git revert` 对应的清单变更并合并，走同一条流水线。

**自动检查更新**：`updates` workflow 每小时检查一次各外部源目录，有比锁定 `ref` 更新的提交时，为该页面开一个 bump PR（分支 `auto-bump/<页面>`）；源目录再次更新时原地刷新同一个 PR，并触发 `ci`。PR 不会自动合并，看过 CI 结果后手动合并，合并即部署。本地可运行 `python -m staticpages updates` 查看。

## 新增前缀（需要审批）

1. 在 `mounts.yaml` 的 `namespaces` 里加 `{ prefix: /xxx/, status: pending }`，然后合并。
2. 手动运行 `routes` workflow：先跑 `plan` 看规则，再跑 `apply`（需要 `routes` environment 审批）。
3. 验证后提 PR，把 `status` 改为 `active`。从这以后部署会清 www 缓存、验证正式地址。

先确认主站没有使用这个前缀：规则生效后，这个前缀下的所有路径都会回源到本仓库。

## 本地运行

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium
.venv/bin/python -m staticpages validate
.venv/bin/python -m staticpages build --smoke     # 组装 dist/ + 检查 + 冒烟测试
.venv/bin/python -m staticpages plan              # 和线上源站对比
.venv/bin/python -m staticpages verify            # 不部署，只校验源站、www 和回归
.venv/bin/python -m staticpages routes plan       # 需要 router key
```

本地凭证从 `.keys/` 读取（已 gitignore），CI 从环境变量读取：

| 环境变量 | 本地文件 | 用途 |
|-|-|-|
| `EDGEONE_PAGES_API_TOKEN` | `.keys/eo_makers_token.txt` | Pages 部署、查询部署状态 |
| `TENCENTCLOUD_DEPLOYER_SECRET_ID/KEY` | `.keys/static-pages-deployer.csv` | 清 www 缓存 |
| `TENCENTCLOUD_ROUTER_SECRET_ID/KEY` | `.keys/static-pages-router.csv` | L7 规则（仅 `routes`） |
| `FEISHU_WEBHOOK` | — | 部署记录通知（可选） |
| `SOURCE_GITHUB_TOKEN` | 本地用 `gh auth token` | 只读拉取私有源仓库（例如 waytoagi-community-intro） |
| `BUMP_GITHUB_TOKEN` | — | `updates` workflow 创建 bump PR（本仓库 Contents + Pull requests 读写） |
| `ORIGIN_URL`（GitHub variable） | `--origin-url` | 覆盖源站地址，自定义域名绑定前用预设域名 |

## GitHub 配置

- **Environment `production`**：存放 `EDGEONE_PAGES_API_TOKEN`、`TENCENTCLOUD_DEPLOYER_SECRET_ID`、`TENCENTCLOUD_DEPLOYER_SECRET_KEY`、`FEISHU_WEBHOOK`，只允许 `main` 分支使用。
- **仓库 secret `SOURCE_GITHUB_TOKEN`**：fine-grained PAT，只给私有源仓库 Contents: Read-only。fork 提交的 PR 拿不到这个 secret，引用私有源的挂载在 fork PR 上会拉取失败。
- **Environment `routes`**：存放 `TENCENTCLOUD_ROUTER_SECRET_ID`、`TENCENTCLOUD_ROUTER_SECRET_KEY`，必须配置审批人。

## 目录

```
mounts.yaml          唯一的挂载清单
sites/               放在本仓库的页面
staticpages/         流水线代码（assemble / checks / smoke / edgeone / verify / routes）
scripts/             一次性运维脚本（bootstrap-cam.py、dns.py）
docs/                设计、runbook（docs/internal/ 为本地内部记录，不提交）
```

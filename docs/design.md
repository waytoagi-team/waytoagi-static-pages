# www.waytoagi.com 静态页挂载流水线：设计方案

状态：已确认方案，实施中（2026-09-27）
负责人：Noodles

## 背景

来源文档：[Opus 5.5 Use Cases：EdgeOne 页面更新记录与操作手册](https://waytoagi.feishu.cn/wiki/K5IvwB8ZfiYjFUkYVQDcnanAnLh)（2026-09-26）

现有流程是把单个页面挂到 `www.waytoagi.com/usecase-atlas/opus5-5/`，全程手工：

```
waytoagi-team/gallery  cases/models/claude-opus-5-5-usecases/
   │ 手工 rsync --delete
   ▼
waytoagi-team/waytoagi-community-intro  usecase-atlas/opus5-5/
   │ git push 触发 EdgeOne Pages
   ▼
kemengopc.waytoagi.com/usecase-atlas/opus5-5/
   │ 每个路径 2 条 L7 规则：rule-3vfh6xhhsck7（308 补斜杠）、rule-3vfh6xhhtr4n（Host+Path 回源）
   ▼
www.waytoagi.com/usecase-atlas/opus5-5/   → 手工 purge_prefix → 手工验证 → 手写飞书记录
```

主站仍回源到原有主站源站，只有挂载路径回源到 Pages。EdgeOne zone：`zone-3tbsf8e3cb9x`。

### 痛点

1. 每个新路径都要手工改 EdgeOne L7 规则，风险最高，也最依赖个人记忆。
2. 同步、校验、清缓存、回归靠人按文档执行，关键约束（按 SHA 确认部署、只清前缀、rsync 目标不能是仓库根）没有机器保证。
3. 挂载页寄居在 `waytoagi-community-intro` / `kemengopc.waytoagi.com`。这两个是有独立意义的实体（社区介绍站），不应承载其他页面。

## 目标

新增或更新一个挂载页 = 提一个 PR 改清单；合并后同步、构建、部署、清缓存、验证、记录全自动；正常情况下不改 EdgeOne 路由。

## 已确认的决策（2026-09-27）

| # | 问题 | 决定 |
|-|-|-|
| 1 | 路由方式 | **前缀（命名空间）方案**：每个前缀一条回源规则，前缀内新增页面不改路由 |
| 2 | 源码位置 | **外部仓库按 SHA 引用**，本仓库 `sites/` 可放少量内联页面 |
| 3 | 部署方式 | **EdgeOne Pages CLI / API 直接部署**，key 由 Noodles 配置 |
| 4 | 与现有实体关系 | **新建通用仓库（本仓库）+ 独立 EdgeOne Pages 项目**，`waytoagi-community-intro` 和 `kemengopc` 保持原样，只把挂载页迁出 |
| 5 | 源站域名 | `static-origin.waytoagi.com`，解析在阿里云 |
| 6 | CI 的 Pages token | 沿用 eo_makers_token（账号级权限，靠 GitHub environment 控制可见范围） |

实现以代码为准，见 [README](../README.md) 和 `staticpages/`。和下文草案的差异：前缀带 `status: pending|active`，用来控制迁移过程中是否清 www 缓存、是否验证正式地址；变更检测依靠源站上发布的 `_static-pages/manifest.json`，不需要额外的状态存储。

## 方案

### 1. 挂载清单 `mounts.yaml`

```yaml
host: www.waytoagi.com
origin: static-origin.waytoagi.com     # 独立 EdgeOne Pages 项目的源站域名（待定）

namespaces:                            # 每个前缀一条 L7 回源规则
  - /usecase-atlas/
  - /p/

mounts:
  - path: /usecase-atlas/opus5-5/
    source:
      repo: waytoagi-team/gallery
      dir: cases/models/claude-opus-5-5-usecases
      ref: b625fa7d7a11a951325dbf094ad653fdf37e2ded
    owner: noodles
    smoke:
      - search: HAProxy
        expect_min: 3
```

仓库结构：

```
mounts.yaml            # 唯一的挂载清单
sites/                 # 本仓库内联页面
scripts/               # assemble / verify / purge / routes
.github/workflows/     # 流水线
edgeone.json           # 缓存头和大文件跳转
middleware.js          # 保留查询参数的补斜杠跳转（构建产物）
docs/                  # 设计与实施记录
```

### 2. 路由

- www 上每个前缀一条 Host + Path 回源规则，初始为 `/usecase-atlas/*` 和 `/p/*`。
- 308 补斜杠由 Pages 的 `middleware.js` 完成并保留原查询参数；`edgeone.json` 静态跳转会丢查询参数，不能用于此处。
- 新增前缀时由 `scripts/routes` 通过腾讯云 API 幂等执行：先 dry-run 输出差异，经 GitHub Environment 人工审批后应用。
- 代价：前缀内不存在的路径返回 Pages 的 404，而不是主站 404。不带斜杠的挂载地址由 Pages 中间件 308，并保留查询参数。
- EdgeOne 免费套餐 L7 规则上限 20 条：每个前缀 1 条，`/_media/*` 1 条；旧规则确认稳定后要尽快删除。

### 3. 流水线（GitHub Actions）

| 阶段 | 内容 |
|-|-|
| PR 检查 | 清单校验（路径不重叠、在已登记前缀内、不占主站保留路径）；按 `source@ref` 组装 `dist/`，每个挂载只写自己的子目录；gitleaks；绝对路径资源引用检查；Playwright 在最终嵌套路径冒烟（JS 错误 0、图片失败 0、`smoke` 断言）；PR 评论贴逐挂载差异 |
| 部署 | EdgeOne Pages CLI 部署 `dist/`，拿到 deploymentId |
| 验证源站 | 变更挂载的 HTML SHA-256 与 `dist/` 一致 |
| 清缓存 | 只对本次变更的挂载 `purge_prefix`，绝不清全站 |
| 验证正式地址 | 正式 URL hash 与源站一致；补斜杠 308 保留探针参数；回归主站 `/`、`/zh`、`/events` 和相邻路径 |
| 记录 | 源 SHA、部署 ID、清缓存任务 ID、hash 自动发飞书 |

更新：改 `ref` 提 PR（可在源仓库加 workflow 自动开 bump PR）。回滚：`git revert` 清单变更，走同一流水线。

### 4. 独立源站与凭证

- 新 EdgeOne Pages 项目 `waytoagi-static-pages`（已创建：`makers-obe4szcie7gs`，中国站，预设域名 `waytoagi-static-pages-tisxqdfu.edgeone.cool`），绑定源站域名（暂定 `static-origin.waytoagi.com`，CNAME 在阿里云 DNS 手工加一次）。
- 缓存：HTML `no-store`（延续微信 WebView 的处理）；图片（webp/png/jpg/jpeg/gif/svg/avif/ico）在 L7 规则的子规则里改为 `public, max-age=604800`，页面原地替换图片时应给 URL 加 `?v=hash`；带 hash 的静态资源长缓存。
- 凭证（GitHub Secrets；本地在 `.keys/`，已 gitignore；不在文档中记录任何密钥内容）：

| 凭证 | 用途 | 权限 | 使用场景 |
|-|-|-|-|
| EdgeOne Pages API Token | `edgeone pages deploy` | 仅新 Pages 项目 | 每次部署 |
| CAM 子用户 `static-pages-deployer` | 清缓存、查任务 | `teo:CreatePurgeTask`、`teo:DescribePurgeTasks`（限 zone）、`teo:DescribeZones` | 每次部署 |
| CAM 子用户 `static-pages-router` | 新增 / 修改前缀路由 | `teo:DescribeL7AccRules`、`teo:CreateL7AccRules`、`teo:ModifyL7AccRule`（限 zone），不给 Delete | 仅新增前缀，需人工审批 |

CAM 策略 JSON 见 [runbooks/create-credentials.md](runbooks/create-credentials.md)。实施记录保存在维护者本地 `docs/internal/log.md`。

### 5. 迁移步骤

1. 建仓库骨架与流水线，先在独立 Pages 项目上跑通 opus5-5。
2. 把 `rule-3vfh6xhhtr4n` 回源改到新源站并扩成 `/usecase-atlas/*` 前缀规则；验证后删除旧 308 规则 `rule-3vfh6xhhsck7`。
3. 从 `waytoagi-community-intro` 删除 `usecase-atlas/opus5-5/`。
4. 接入 STD-011，运营按模板提 PR 出页（可复用 `eo-makers-template`）。

## 待确认

- [ ] `community-growth-deck` 属于社区介绍站（不动）还是挂载页（一起迁）
- [x] 源站域名：`static-origin.waytoagi.com`
- [x] EdgeOne Pages CLI 部署能返回 deploymentId（实测 `dpiu7a79upmi`、`dpt6iiyficen`）
- [x] `edgeone.json` 的 Pages 308 跳转丢查询参数；改由 Pages 中间件构造完整目标 URL，保留查询参数（2026-09-28）

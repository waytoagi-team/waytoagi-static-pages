# /kemengopc/ 迁移与回滚

源码来自 `waytoagi-team/waytoagi-community-intro` 根目录，清单的 `source.dir` 写空字符串（`git archive <sha>:`），不能写 `.`。保留根目录的 4 个 HTML、`images/` 和 `assets/`，排除其他挂载、开发脚本与预览图。中文文件名由逐文件校验器做 URL 编码。

## 首次切换

1. 以 `pending` 发布挂载，CI 与浏览器冒烟通过后，部署到 `https://static-origin.waytoagi.com/kemengopc/`。
2. 逐文件比较 `dist/kemengopc/<文件>`、旧源站 `https://kemengopc.waytoagi.com/<文件>`、新源站 `https://static-origin.waytoagi.com/kemengopc/<文件>` 的 SHA-256。旧源站取根路径，带缓存探针参数；切换前再次核对源仓库版本，防止迁移期间更新。
3. 用 `DescribeL7AccRules` 保存当前完整规则到本地 `docs/internal/snapshots/`，包括规则内容、ID、优先级。快照不提交仓库。
4. 仅原位更新回源规则 **`rule-3umlkdq1unp5`**：用 `routes.desired_rule(manifest, '/kemengopc/')` 生成标准规则，再附上原 RuleId，通过 `ModifyL7AccRule` 提交。这样统一规则命名、回源域名和 Host，且移除旧的 `UpstreamURLRewrite: rmvPrefix /kemengopc`。新源站需要完整的 `/kemengopc/` 路径。此步骤不增加规则数量。
5. **保留 `rule-3umlkdq1t94p` 全部内容**。该共享规则负责 apex → www、HTTP → HTTPS 和 `/kemengopc` → `/kemengopc/`（保留查询参数）。`routes plan` 可能将其列为 legacy note，这不是停用依据。此路径不能照通用手册停用旧跳转规则，也不能在接管前直接执行 `routes apply` 创建重复规则。
6. 只对 `https://www.waytoagi.com/kemengopc/` 执行 `purge_prefix`，等待任务成功。校验正式 URL 与所有发布文件，检查中文 HTML 链接、图片、翻页和移动端；检查共享跳转保留查询参数，并回归 `/`、`/zh`、`/events`、已有两个挂载。用仅旧源站存在的 `preview-contact-sheet.png` 确认新路由返回 404。
7. 验收通过后，将 namespace 改为 `active` 并合并。仅修改状态不会让内容差异检测触发重新部署，因此第 6 步的清缓存与验收必须显式执行，不能只依赖状态变更触发的 workflow。用 `routes plan` 确认该前缀无待修改动作。

## 回滚

如果旧域名首页跳转已启用，**先撤销旧项目的 `middleware.js` 并等待其生产部署完成**，确认 `https://kemengopc.waytoagi.com/` 和 `/index.html` 直接返回 200 后，再恢复以下回源规则。否则 www 回源旧站时会收到跳回自身的 301。

从切换前快照提取 `rule-3umlkdq1unp5`，使用其 `RuleId`、`RuleName`、`Description`、`Status` 和 `Branches` 调用 `ModifyL7AccRule` 恢复原规则（包含旧回源、Host 与前缀重写）；不要把只读的优先级字段提交给修改接口。再次清理 `/kemengopc/` 前缀缓存，验证正式地址回到旧源站，并将 namespace 改回 `pending`。只 revert 清单不能恢复路由；回滚后不要运行 `routes apply`，它会按清单重新创建新源站规则。

保留旧 `kemengopc.waytoagi.com` 站点及根目录文件作为回退入口。共享跳转规则始终保留。

## 旧域名首页重定向

由旧源仓库 [waytoagi-community-intro 的 middleware.js](https://github.com/waytoagi-team/waytoagi-community-intro/blob/main/middleware.js) 管理，通过旧 Pages 项目 `makers-2rs9t5wqaiwt` 的 Git 部署发布。只匹配 Host `kemengopc.waytoagi.com` 的 `/` 和 `/index.html`，301 到 `https://www.waytoagi.com/kemengopc/`，原始查询参数完整保留；其他 Host、图片、历史 HTML 与子目录继续放行。

该中间件不属于共享站点的发布资源，清单明确排除 `middleware.js`，避免后续 bump 引入旧项目的路由配置。www 仍使用 `static-origin.waytoagi.com` 回源。

实现采用 [Pages 中间件](https://cloud.tencent.com/document/product/1552/127609)；`edgeone.json` 静态跳转在此前测试中会丢失查询参数。旧域名所属 Pages zone 的通用 L7 规则虽可创建，但本次实际请求未生效，测试规则已删除，未留下第二套跳转配置。

## 后续更新

源仓库按原方式维护内容，本仓库的 `updates` workflow 自动提出 SHA bump PR，CI 通过并合并后部署到正式路径。根目录源会跟踪源仓库所有提交；其他子目录的修改也可能触发 bump PR，部署阶段仍按排除后的发布文件哈希判断内容是否变化。

## 2026-09-27 切换记录

- 源码：`waytoagi-team/waytoagi-community-intro@4333ddbb1a914f6d4e6e1f206fb0b9c45aa9d7d9` 根目录，72 个发布文件；旧源站、新源站和正式地址逐文件 SHA-256 一致。
- 部署：`dpvb0aur8njn`，由 [GitHub deploy run 36311162831](https://github.com/waytoagi-team/waytoagi-static-pages/actions/runs/36311162831) 发布并验证成功。
- 18:06（UTC+8）原位接管 `rule-3umlkdq1unp5`；其余 19 条规则内容未变。清缓存仅针对 `https://www.waytoagi.com/kemengopc/`，任务 `3vi9rpip8mca` 成功。
- 18:09（UTC+8）验收通过：三个挂载的正式首页与补斜杠、主站 `/`、`/zh`、`/events`、HTTPS/www 跳转及查询参数保留；旧源站独有的 `preview-contact-sheet.png` 在正式路径返回 404，确认已走新源站。
- 新源站桌面与手机浏览器检查：28 页导航正常，图片损坏 0、JavaScript 错误 0。
- 回滚快照保存在维护者本地 `docs/internal/snapshots/kemengopc-before-20260927T095819Z.json`，详细执行记录在 `.state/kemengopc-cutover.json`；旧源站继续保留。

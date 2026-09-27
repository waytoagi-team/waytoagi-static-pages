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

从切换前快照提取 `rule-3umlkdq1unp5`，使用其 `RuleId`、`RuleName`、`Description`、`Status` 和 `Branches` 调用 `ModifyL7AccRule` 恢复原规则（包含旧回源、Host 与前缀重写）；不要把只读的优先级字段提交给修改接口。再次清理 `/kemengopc/` 前缀缓存，验证正式地址回到旧源站，并将 namespace 改回 `pending`。只 revert 清单不能恢复路由；回滚后不要运行 `routes apply`，它会按清单重新创建新源站规则。

保留旧 `kemengopc.waytoagi.com` 站点及根目录文件作为回退入口。共享跳转规则始终保留。

## 后续更新

源仓库按原方式维护内容，本仓库的 `updates` workflow 自动提出 SHA bump PR，CI 通过并合并后部署到正式路径。根目录源会跟踪源仓库所有提交；其他子目录的修改也可能触发 bump PR，部署阶段仍按排除后的发布文件哈希判断内容是否变化。

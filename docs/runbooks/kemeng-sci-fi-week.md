# 科梦科幻周

正式入口：https://www.waytoagi.com/kemeng-sci-fi-week （Pages 补尾斜杠）。
源仓库 `waytoagi-team/aj-kemeng-fusion` 根目录，固定版本见 `mounts.yaml`。
页面包含 22 页演示及 69 个资源，视频按现有 media 规则转存 OSS。

## 首次上线

1. 以 pending namespace 合并挂载，等待 deploy 成功；验证 static-origin 上的页面和资源。
2. routes workflow 先 plan、再 apply，`only=/kemeng-sci-fi-week/`，按 routes environment 的审批流程执行。
3. 在 infra-deployments 中运行 `tools/phase2/eo_origin_token.py strip-static` 先看计划，再加 `--execute`，使回源令牌删除规则覆盖新静态路径；`status` 确认无漏项。
4. 验证正式地址、补尾斜杠时保留查询参数、演示翻页与资源，以及官网 `/`、`/zh`、`/events` 和已有挂载。
5. 将 namespace 改为 active 并合并，然后手动执行 deploy workflow（force=true）。仅修改状态可能因内容未变化而跳过清缓存与正式地址验证。

## 更新与回滚

更新源仓库后，通过此仓库的 SHA bump PR 验证并发布。内容回滚恢复之前验证过的 ref。
首次路由异常时，使用 routes status 停用本路径新建规则，将 namespace 恢复 pending；不改其他路径的规则。

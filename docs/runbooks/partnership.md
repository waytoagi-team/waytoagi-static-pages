# 对外合作介绍

入口：https://www.waytoagi.com/partnership/ （裸路径由 Pages 补尾斜杠）。
源仓库：waytoagi-team/waytoagi-partnership-20261109，完整版本见 mounts.yaml。
50 页静态演示，保留源码相对路径，排除部署说明与原部署清单。

## 首次发布

1. pending 挂载合并后等待 deploy 源站发布与逐文件校验通过。
2. 当前 L7 已有 20 条规则；本路径通过 route_with 复用科梦的 `rule-3xf7y5ibs6mv`。
   routes workflow 的 only 输入 `/partnership/`，计划应仅原位修改这条规则，保留科梦两种路径并加入 partnership 两种路径。
   审批后 apply。保留规则原状快照，绝不删除或停用其他规则。
3. infra-deployments 的 `eo_origin_token.py strip-static` 先 dry-run 再 --execute，status 确认无漏项。
4. 核对正式文件、补斜杠查询参数、50 页导航；回归科梦与官网已有入口。
5. namespace 改 active 并合并，手动 deploy（force=true），刷新缓存并验证正式入口。

## 回滚与更新

内容更新或回滚通过固定 source.ref 的 PR 执行。
首次切流回滚须恢复共享规则原条件，只撤 `/partnership` 和 `/partnership/*`，保留科梦路径；
**不能停用整条共享规则**。清理 partnership 缓存；从清单同时撤掉 partnership namespace 与挂载，再按 `/kemeng-sci-fi-week/` plan/apply，避免下一次 apply 重新加回已撤路径。

## 2026-11-15 上线验收

- 内容发布 run `43624383513` 成功；用户批准 routes run `43625020301` 后完成共享规则原位更新。
- 回源令牌删除规则已补齐 partnership 裸路径和子路径，status 无漏项。
- 正式地址 231 个文件及科梦页面文件哈希校验通过；补斜杠、查询参数和官网回归通过。
- 生产页面 50 页、上一页/下一页和目录功能通过，未捕获 JavaScript 错误。
- 首次浏览器等待完整 load 超时；改为等待 DOM 和页面控件就绪后完成交互测试，全部静态文件另经 HTTP 哈希验证。

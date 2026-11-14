# 抖音 AI 夜校

入口：https://www.waytoagi.com/douyin-ai-night-school/
源仓库：waytoagi-team/douyin-ai-night-school，固定版本读取 dist/。
源码修改后运行 npm run build 并提交产物；16 个页面含 13 期课程、66 场课次（含两场开营）。
生成的链接使用相对路径；飞书资料与回放沿用原平台权限。

## 首次发布

1. pending PR 合并，等待源站部署和文件校验。
2. routes plan/apply --only=/douyin-ai-night-school/，经 routes environment 审批。
   复用 rule-3xf7y5ibs6mv，只增加新路径的裸路径和通配路径，保留科梦和 partnership。
3. infra-deployments 中 eo_origin_token.py strip-static 先 dry-run 再 --execute，status 无漏项。
4. 验证正式页面、资源、课程搜索、进度保存、继续学习、成果页与主站回归。
5. namespace 改 active，合并后 deploy force=true 刷缓存并完成正式验收。

## 回滚

内容回滚通过 source.ref PR。撤入口先从清单移除本 namespace 和 mount，
按 /kemeng-sci-fi-week/ plan/apply，仅撤夜校路径；不能禁用共享规则。

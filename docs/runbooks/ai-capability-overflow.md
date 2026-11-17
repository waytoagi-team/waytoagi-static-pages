# 能力溢出之后，我们做什么

公开入口：https://www.waytoagi.com/ai-capability-overflow/
源仓库：waytoagi-team/aj-ai-course（私有），main 版本固定在 mounts.yaml。
发布根目录 index.html 和 assets/，排除源稿 src/、README 和独立讲稿、说明。
页面自带的讲稿功能保留。视频由现有流水线转存 OSS，引用无需修改。

## 首次发布

1. pending PR 检查通过并合并，确认 CI 的 SOURCE_GITHUB_TOKEN 可读私有源仓库，等待源站文件校验成功。
2. routes plan/apply --only=/ai-capability-overflow/，通过 routes environment 审批。
   原位扩展共享规则 rule-3xf7y5ibs6mv，仅加入本路径的裸路径和通配路径，保留其他页面。
3. infra-deployments 的 eo_origin_token.py strip-static 先 dry-run 再 --execute，status 无遗漏。
4. 验证正式文件、视频跳转、查询参数、翻页、跳页和讲稿功能，回归主站。
5. namespace 改 active，合并后 deploy force=true 刷新缓存并校验。

## 更新与回滚

AJ 更新 index.html 和 assets 后通过固定 source.ref 的 PR 发布。
首次入口回滚仅从清单移除本 namespace 和 mount，再按 /kemeng-sci-fi-week/ plan/apply，
绝不能禁用共享规则。内容回滚恢复之前的 source.ref 并重新发布。

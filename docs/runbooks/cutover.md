# 把一个前缀切到 static-origin

适用场景：一个前缀原来由旧规则回源别处（例如 kemengopc），现在要改为由本仓库的源站提供。

## 前置条件

- 挂载页已经在 `mounts.yaml` 中，前缀状态为 `pending`，`python -m staticpages verify` 通过（新源站内容正确）。
- **`dist/` 与旧源站逐文件一致**：直接请求旧源站（例如 `kemengopc.waytoagi.com/<路径>/<文件>?t=<时间戳>`）比对 SHA-256，**不要用正式域名比对**，正式域名可能返回旧缓存。2026-09-27 opus5-5 就因为比对了 www 缓存，把 ref 锁在了旧版本，切换后 www 回退。
- 切换当天通知仍在用旧流程更新页面的人，之后改为通过本仓库修改 `ref`。
- 找一个**探针**：只在旧源站存在、新源站不存在的文件（例如点文件 `.gitignore`，新源站不发布点文件），用来确认 www 实际走的是哪个源站。

## 步骤

```bash
python -m staticpages routes plan       # 预期：create 前缀规则；note 列出要退役的旧规则
python -m staticpages routes apply      # 新建规则（router key）
python -m staticpages routes status <旧回源规则> disable   # 先停用、不删除，可以回滚
python -m staticpages routes status <旧跳转规则> disable
curl -s -o /dev/null -w '%{http_code}' "https://www.waytoagi.com/<挂载路径>/.gitignore?probe=1"   # 404 = 已走新源站
```

然后在 `mounts.yaml` 里把该前缀改为 `status: active`，运行：

```bash
python -m staticpages deploy --force --smoke   # 部署 → 校验源站 → 清 www 缓存 → 验证正式地址和回归
```

## 回滚

```bash
python -m staticpages routes status <旧回源规则> enable
python -m staticpages routes status <旧跳转规则> enable
python -m staticpages routes status <新前缀规则> disable
```

然后把 `mounts.yaml` 里的前缀改回 `pending`，并对挂载路径执行 `purge_prefix`。

## 收尾

稳定运行一段时间后（建议一周），删除已停用的旧规则。router key 没有删除权限，需要用 `TencentCloudSecretKey` 或在控制台删除。旧源站仓库里对应的子目录也一并删除。

## 记录

| 前缀 | 新规则 | 已停用的旧规则 | 切换时间 |
|-|-|-|-|
| `/usecase-atlas/` | rule-3vi6scsksy31 | rule-3vfh6xhhtr4n（回源）、rule-3vfh6xhhsck7（跳转） | 2026-09-27 |
| `/community-growth-deck/` | rule-3vi6zsyyc7tr | rule-3vgmsv329iwc（回源）、rule-3vgmsv3284bw（跳转） | 2026-09-27 |

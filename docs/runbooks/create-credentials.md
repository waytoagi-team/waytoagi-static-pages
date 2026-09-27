# 创建流水线凭证

一次性操作。密钥文件放在 `.keys/`（已 gitignore），不要写进任何文档或提交。

> 第 1、2 步已于 2026-09-27 用脚本完成：
> `python scripts/bootstrap-cam.py`（dry-run）/ `--apply`（创建），可重复运行，主账号 ID 自动从调用者身份获取。需要有 CAM 写权限的 key，默认读取 `.keys/TencentCloudSecretKey.csv`。
> 下面的控制台步骤作为手工备选保留。

## 1. CAM 策略（控制台 → CAM → 策略 → 按策略语法创建）

`static-pages-deployer`：

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": ["teo:CreatePurgeTask", "teo:DescribePurgeTasks"],
      "resource": ["qcs::teo::uin/<主账号 ID>:zone/zone-3tbsf8e3cb9x"]
    },
    {
      "effect": "allow",
      "action": ["teo:DescribeZones"],
      "resource": ["*"]
    }
  ]
}
```

`static-pages-router`：

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": ["teo:DescribeL7AccRules", "teo:CreateL7AccRules", "teo:ModifyL7AccRule"],
      "resource": ["qcs::teo::uin/<主账号 ID>:zone/zone-3tbsf8e3cb9x"]
    }
  ]
}
```

## 2. 子用户（CAM → 用户 → 新建子用户）

| 用户名 | 访问方式 | 关联策略 | 密钥保存到 |
|-|-|-|-|
| `static-pages-deployer` | 仅编程访问 | `static-pages-deployer` | `.keys/static-pages-deployer.csv` |
| `static-pages-router` | 仅编程访问 | `static-pages-router` | `.keys/static-pages-router.csv` |

## 3. EdgeOne Pages

> 2026-09-27 已完成第 1 项：项目 `waytoagi-static-pages`（`makers-obe4szcie7gs`，中国站）由 `edgeone makers deploy -n` 自动创建，token 使用的是 `eo_makers_token.txt`。

> 第 3 项（2026-09-27）实际操作：Noodles 在控制台绑定域名并点击免费证书，Claude 用 API 加 DNS。
> 对应的 API 如下。`--bind` 和 `--cert` 调用的接口与控制台一致，但在全新域名上纯 API 跑通尚未独立验证：
> ```bash
> python scripts/pages-domain.py --bind static-origin.waytoagi.com   # teo CreatePagesResources / pages:CreatePagesZoneCustomDomain
> python scripts/pages-domain.py                                     # 查看分配的 CNAME 目标
> python scripts/dns.py static-origin <CNAME 目标> --apply           # 阿里云解析
> python scripts/pages-domain.py --wait static-origin.waytoagi.com   # 等待 online
> python scripts/pages-domain.py --cert static-origin.waytoagi.com   # ModifyHostsCertificate eofreecert
> ```

1. 在 EdgeOne Pages 控制台新建项目 `waytoagi-static-pages`（直接上传类型，不绑 Git）。
2. 生成 API Token，保存为 `.keys/edgeone_pages_token.txt`。
3. 绑定源站域名（暂定 `static-origin.waytoagi.com`），在阿里云 DNS 加对应 CNAME。

## 4. GitHub Secrets（仓库建好后）

| Secret | 来源 |
|-|-|
| `EDGEONE_PAGES_API_TOKEN` | `.keys/edgeone_pages_token.txt` |
| `TENCENTCLOUD_DEPLOYER_SECRET_ID` / `_KEY` | `.keys/static-pages-deployer.csv` |
| `TENCENTCLOUD_ROUTER_SECRET_ID` / `_KEY` | `.keys/static-pages-router.csv`，放在需审批的 Environment `routes` 中 |

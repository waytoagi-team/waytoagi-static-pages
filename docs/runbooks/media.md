# 大文件转存（OSS + www /_media/*）

EdgeOne Pages 单文件上限 25MB。超过 `mounts.yaml` 里 `media.min_bytes`（20MB）的文件，以及匹配 `media.always`（`*.mp4` / `*.mov` / `*.webm`）的文件，不会发布到 Pages，而是转存到 OSS。

## 工作方式

```
源码仓库里的 assets/big.mp4
  ├─ 部署时上传 → oss://waytoagi-static-pages-media/_media/<sha256>.mp4
  │                （Content-Type、Cache-Control: public, max-age=31536000, immutable、x-oss-meta-sha256）
  └─ Pages：/<页面>/assets/big.mp4 302 跳转到 https://www.waytoagi.com/_media/<sha256>.mp4
www /_media/* → EdgeOne L7 规则（routes 管理）→ 私有 OSS（S3 协议，v4 签名），节点缓存一年，缓存键忽略查询参数
```

- 页面照常用相对路径引用，作者不需要做任何事。
- 文件名就是内容哈希：内容一变，URL 就变，**永远不需要清缓存**。回滚时旧对象还在，跳转会自动指回去。
- 跳转目标写成绝对的 www 地址，因为 `/_media/*` 规则只在 www 上存在。
- 浏览器缓存头来自 OSS 对象元数据。EdgeOne 的 `ModifyResponseHeader` 对 AWSS3 源站不生效（2026-09-27 验证）。

## 放不进 git 的文件（大于 100MB，或已经在别的 OSS 上）

```bash
python scripts/media-import.py <本地文件> ...
python scripts/media-import.py --src-key <能读源 bucket 的 AccessKey CSV> oss://<bucket>/<key> ...
```

脚本会输出 `https://www.waytoagi.com/_media/<sha256>.<ext>`，页面里直接引用这个地址。可以重复运行。

## 凭证

| RAM 子用户 | 权限（仅 `waytoagi-static-pages-media/_media/*`） | 用在哪里 |
|-|-|-|
| `static-pages-media-upload` | PutObject、GetObject | `production` environment：`ALIYUN_MEDIA_UPLOAD_KEY_ID/SECRET` |
| `static-pages-media-origin` | GetObject | EdgeOne 回源规则；`routes` environment：`ALIYUN_MEDIA_ORIGIN_KEY_ID/SECRET` |

创建或补建：`python scripts/bootstrap-ram.py --key <管理员 AccessKey CSV> [--apply]`。

## 回源规则

```bash
python -m staticpages routes plan --only /_media/
python -m staticpages routes apply --only /_media/
```

EdgeOne 对 AWSS3 源站的限制：不能带端口字段，也不能写 `OriginProtocol`（写 https 就会要求带端口）。免费套餐规则上限是 20 条。

## 排查

```bash
curl -sI https://www.waytoagi.com/_media/<key>              # 200、server: AliyunOSS、cache-control immutable
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://static-origin.waytoagi.com/<页面>/<文件>   # 302 → www/_media
```

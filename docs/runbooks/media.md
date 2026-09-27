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
- `build` 的敏感内容检查覆盖 Pages 文件和本次转存的 OSS 文件，25MB 限制只检查 Pages 文件。CI 和部署还执行 `python -m staticpages scan-secrets --gitleaks ./gitleaks`，扫描 `dist/` 及构建清单引用的 OSS 缓存文件，不设置扫描文件大小上限。
- `media.prefix` 不能使用主站保留路径（如 `/api/`、`/_next/`、`/static/`），也不能与已登记 namespace 重叠。

## HTML / CSS 不会转存：太大时 CI 拒绝

`.html` / `.htm` / `.css` 会按自己的地址解析相对 URL（页面里的 `src="img/a.png"`、CSS 里的 `url(font.woff2)`），302 到 `/_media/<hash>` 之后这些引用都会失效。所以这类文件**始终留在 Pages**，一旦达到 `media.min_bytes`（20MB），CI 直接拒绝，并在报错里给出拆分建议：

- 页面里内嵌的数据（大段 JSON、base64 图片/字体/视频、大型内联脚本）拆成同目录下的 `.json` / `.js` / 资源文件，按相对路径加载；必要时把一个页面拆成多个页面；
- CSS 里内嵌的 base64 字体或图片拆成单独文件，用相对路径的 `url()` 引用。

拆出来的大资源文件会被自动转存。注意：普通 `<script src>` 加载的 JS 可以转存；**带相对 `import` 的 ES module** 转存后会失效，这种 JS 应拆小，保持在 20MB 以下。

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

### 轮换回源凭证

先更新 `routes` environment 的 `ALIYUN_MEDIA_ORIGIN_KEY_ID` 和 `ALIYUN_MEDIA_ORIGIN_KEY_SECRET`。规则比较会检查 AccessKey ID、Region 和 SignatureVersion；日志不会输出 ID 或 Secret。

EdgeOne 查询接口会遮蔽 SecretAccessKey，因此需要显式刷新才能保证 Secret 被写入：

```bash
python -m staticpages routes plan --only /_media/ --refresh-media-credentials
python -m staticpages routes apply --only /_media/ --refresh-media-credentials
```

GitHub `routes` 工作流同样提供 `refresh_media_credentials` 选项，配合 `only=/_media/`，先运行 `plan`，再运行 `apply`。本地执行时须先更新环境变量或 `.keys/static-pages-media-origin.csv`。确认新凭证回源成功后再撤销旧凭证；已有缓存的 `200` 响应不能证明新凭证有效，应使用尚未经过 CDN 缓存的对象验证。

## 排查

```bash
curl -sI https://www.waytoagi.com/_media/<key>              # 200、server: AliyunOSS、cache-control immutable
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://static-origin.waytoagi.com/<页面>/<文件>   # 302 → www/_media
```

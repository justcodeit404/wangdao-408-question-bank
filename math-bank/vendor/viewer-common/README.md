# viewer-common

数学 / 408 / 政治题库共用的轻量底座：

| 文件 | 职责 |
|------|------|
| `storage.js` | `safeSetItem`、JSON 读写、**分片 map**（marks 等大对象拆 key） |
| `platform-sync.js` | 平台登录探测（httpOnly cookie）、`sync-from-bank` |
| `scratch-ink.js` | Canvas 笔迹纯逻辑、归一化坐标与内存会话 |
| `scratch-pad.css` | 草稿板响应式分屏（可拖拽分隔条 + 一键放大）、主题与触控隔离样式 |
| `scratch-pad.js` | 题库宿主自动发现、Canvas 草稿板、分屏拖拽/比例记忆与生命周期管理 |
| `scratch-ink.test.js` | `scratch-ink.js` 的零依赖 Node assert 测试 |
> 注：政治移动端逻辑由生成脚本内联产出（各 `app.html` 内联），`politics-mobile.js` / `.css` 不再分发（历史文件已删除）。

## 挂载

平台启动时挂载：

```
/banks/common  →  apps/viewer-common
```

题库页在平台下引用：

```html
<script src="/banks/common/storage.js"></script>
<script src="/banks/common/platform-sync.js"></script>
```

## 独立端口副本（必须同步）

独立端口（8123 / 8080 / 8124）用相对路径副本：

- `apps/bank-math/vendor/viewer-common/`
- `apps/bank-408/math-bank/vendor/viewer-common/`
- `apps/bank-politics/vendor/viewer-common/`

**改本目录任意文件后必须跑：**

```powershell
powershell -File tools/sync_viewer_common.ps1
```

仅检查漂移（exit 1 = 有漂移）：

```powershell
powershell -File tools/sync_viewer_common.ps1 -CheckOnly
```

日常刷题优先走平台 `/banks/*`（同源 cookie）；独立端口仅调试用。

## 不做什么

- 不合并两套题型渲染逻辑
- 不改 localStorage 业务 key 前缀（避免用户进度丢失）

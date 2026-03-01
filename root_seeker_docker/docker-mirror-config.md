# Docker 国内镜像加速配置（绕过 Docker Hub 连接问题）

因网络原因无法连接 Docker Hub 时，可配置国内镜像源加速拉取镜像。

> **⚠️ 风险提示**：错误配置可能导致 Docker 无法启动。建议先备份原配置，并优先使用图形界面方式。

## 配置前备份（推荐）

```powershell
# 备份 daemon.json（若存在）
Copy-Item "$env:ProgramData\Docker\config\daemon.json" "$env:ProgramData\Docker\config\daemon.json.bak" -ErrorAction SilentlyContinue
```

## 若 Docker 无法启动的恢复方法

1. 删除或重命名 `C:\ProgramData\Docker\config\daemon.json`
2. 或从备份恢复：`Copy-Item daemon.json.bak daemon.json`
3. 重启 Docker Desktop

## 方法一：Docker Desktop 图形界面（推荐，风险最低）

1. 右键点击任务栏右下角 **Docker 图标**
2. 选择 **Settings（设置）**
3. 左侧选择 **Docker Engine**
4. 在右侧 JSON 配置中，找到或添加 `registry-mirrors` 字段：

```json
{
  "builder": {
    "gc": {
      "defaultKeepStorage": "20GB",
      "enabled": true
    }
  },
  "experimental": false,
  "registry-mirrors": [
    "https://docker.xuanyuan.me",
    "https://docker.1panel.live",
    "https://hub.rat.dev",
    "https://docker.m.daocloud.io"
  ]
}
```

5. 点击 **Apply & Restart** 等待 Docker 重启生效

## 方法二：直接编辑配置文件

### Windows 路径

- Docker Desktop：`C:\ProgramData\Docker\config\daemon.json`
- 若不存在，可创建 `%UserProfile%\.docker\daemon.json`

### 配置内容

创建或编辑 `daemon.json`，内容如下（保留原有其他配置，仅添加或修改 `registry-mirrors`）：

```json
{
  "registry-mirrors": [
    "https://docker.xuanyuan.me",
    "https://docker.1panel.live",
    "https://hub.rat.dev",
    "https://docker.m.daocloud.io"
  ]
}
```

保存后重启 Docker Desktop。

## 当前可用免费镜像源（2025 年）

| 地址 | 说明 |
|------|------|
| https://docker.xuanyuan.me | 轩辕镜像免费版，稳定性较好 |
| https://docker.m.daocloud.io | DaoCloud 镜像 |
| https://docker.1panel.live | 1Panel 社区镜像 |
| https://hub.rat.dev | RatPanel 社区镜像 |
| https://docker.1ms.run | 1ms 镜像 |
| https://dockerpull.org | 备用源 |
| https://docker-mirror.aigc2d.com | AIGC2D 镜像 |

**建议**：可配置 2～3 个源，Docker 会依次尝试；若某个源拉取失败，会自动切换下一个。

## 常见导致启动失败的配置错误

- JSON 格式错误（多余逗号、引号不匹配）
- 镜像地址拼写错误或协议错误（需 `https://`）
- 手动编辑时误删其他必要字段

**建议**：优先用 Docker Desktop 图形界面配置，可自动校验格式。

## 验证配置

```powershell
docker info
```

在输出中查找 `Registry Mirrors`，应显示已配置的镜像地址。

## 拉取测试

```powershell
docker pull hello-world
```

能成功拉取即表示配置生效。

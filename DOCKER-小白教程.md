# 单用户版 Docker 小白教程

本教程按 Windows + Docker Desktop + 本机使用编写。单用户版只在你的电脑上运行，不需要注册面板账号，也不需要设置公网域名。

## 1. 安装 Docker Desktop

从 [Docker Desktop 官方下载页](https://www.docker.com/products/docker-desktop/)下载安装 Windows 版本并启动。等 Docker Desktop 显示 **Engine running** 后再继续。如果安装程序要求启用 WSL 2，按提示完成并重启电脑。

## 2. 下载启动文件

打开开始菜单，搜索 **PowerShell** 并打开，然后复制执行：

```powershell
$appDir = Join-Path $env:USERPROFILE 'DouYinSparkFlow-SingleUser'
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Set-Location $appDir
Invoke-WebRequest 'https://raw.githubusercontent.com/BARONCMH/DouYinSparkFlow-SingleUser/main/compose.yml' -OutFile 'compose.yml'
New-Item -ItemType Directory -Force -Path 'data/config','data/logs' | Out-Null
```

## 3. 启动并打开

在同一个 PowerShell 窗口执行：

```powershell
docker compose up -d
docker compose ps
```

第一次启动会下载 Docker 镜像，稍等几分钟。状态显示 `Up` 后，打开 [http://localhost:18081](http://localhost:18081)。新增抖音号后点“开始扫码授权”，用抖音 App 扫描网页上的二维码登录。

## 4. 日常操作

查看日志：

```powershell
docker compose logs -f
```

按 `Ctrl+C` 只会退出日志查看。更新程序：

```powershell
docker compose pull
docker compose up -d
```

关闭程序：

```powershell
docker compose down
```

再次打开 PowerShell，先执行 `Set-Location "$env:USERPROFILE\DouYinSparkFlow-SingleUser"`，再执行 `docker compose up -d`。

## 5. 重要说明

- 账号配置、目标好友和加密后的登录状态保存在 `data/config`；运行记录保存在 `data/logs`。备份或迁移时保留整个 `data` 文件夹。
- 这个版本默认只允许本机访问。不要把 18081 端口直接开放到互联网，也不要把 `data` 文件夹或登录 Cookie 发给别人。
- Docker Desktop 必须保持运行，面板才能工作。重启电脑后 Docker 会按 Compose 的设置自动恢复容器。

## 常见问题

- **Docker 命令无法连接**：先启动 Docker Desktop 并等待 Engine running。
- **网页打不开**：执行 `docker compose ps` 和 `docker compose logs --tail 100` 检查容器状态。
- **镜像下载失败**：检查网络能否访问 `ghcr.io`，稍等后运行 `docker compose pull` 重试。

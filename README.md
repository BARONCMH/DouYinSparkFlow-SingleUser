# DouYinSparkFlow 单用户版

这是现有面板的本地单用户版本。它只服务当前机器上的一个使用者，但可以在同一个控制台中保存多个抖音号。每个抖音号可以分别配置 Cookie、目标好友、发送时间、消息模板和发送间隔。

GitHub 仓库：[BARONCMH/DouYinSparkFlow-SingleUser](https://github.com/BARONCMH/DouYinSparkFlow-SingleUser)

## 已移除的功能

- 普通用户登录、注册和退出登录
- 管理员登录、管理员控制台、用户管理
- 兑换码、时长、试用期和授予时长
- 多用户权限、账号归属和管理员公告/定向消息

## 保留的功能

- 多个抖音号的新增、编辑和删除
- 抖音 App 扫码授权、二级短信验证码、验证方式自动选择和可点击实时画面
- 重启授权、手动 Cookie 导入和登录状态检测
- 已保存登录状态的检测
- 单个账号发送、全部账号发送、停止发送
- 每个抖音号的目标好友、消息模板、间隔和定时发送时间
- 发送记录和运行日志

## Windows 直接运行（不需要 Docker）

需要安装 Python 3.12。第一次运行会在本目录创建 `.venv`，安装 Python 依赖并下载 Playwright Chromium，之后直接打开本机面板：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& .\start-single-user.ps1
```

如果 PowerShell 阻止脚本，先执行上面的 `Set-ExecutionPolicy`。浏览器打开 <http://127.0.0.1:18081/>。

## Docker 运行（推荐给不想安装 Python 的用户）

请按[单用户版 Docker 小白教程](DOCKER-小白教程.md)操作。Docker 镜像会自动下载 Chromium，配置和日志保存在本机 `data` 文件夹，不需要克隆源码或手动安装 Python。

如果已克隆本仓库，也可在仓库目录执行：

```powershell
docker compose -f compose.yml up -d
```

然后打开 <http://127.0.0.1:18081/>。数据保存在 `data`，不会写入生产面板的配置目录。

停止本地版本：

```powershell
docker compose -f compose.yml down
```

单用户版默认只允许本机访问，不要将端口直接开放到公网。

# TVGuard NAS 部署指南

前提：NAS 上已装 Docker（群晖/威联通的 Container Manager/Container Station 自带）。
以下按「SSH 命令行」为主流程（所有 NAS 通用），群晖不想开 SSH 的看文末 GUI 备选。

> **飞牛 fnOS 用户直接看文末「飞牛专属流程」，比通用流程更简单。**

## 一、把项目传到 NAS

在电脑上把整个 `tvguard` 目录传到 NAS，任选其一：

- **SMB 共享**：直接复制粘贴到 NAS 共享文件夹，比如放到 `/volume1/docker/tvguard`
- **scp**：`scp -r tvguard user@nas-ip:/volume1/docker/`

目录里只需要这些文件（`data/` 可以不传，会自动创建）：

```
tvguard/
├── Dockerfile  docker-compose.yml  requirements.txt  .dockerignore
├── run.py  config.example.yaml  README.md
└── tvguard/  （源码目录，含 templates）
```

## 二、写配置文件

SSH 登录 NAS：

```bash
ssh user@nas-ip
cd /volume1/docker/tvguard    # 按你的实际路径
cp config.example.yaml config.yaml
vi config.yaml                # 把 adb_host 改成雷鸟电视的 IP；建议设置 password
```

> 电视 IP 查法：电视 设置 → 关于 → 网络状态。建议同时到路由器里给电视固定 IP，
> 否则电视 IP 变了服务就失联。

## 三、启动

```bash
docker compose up -d --build   # 首次构建约几分钟
docker compose logs -f         # 看日志，确认服务起来
```

验证：手机浏览器打开 `http://<NAS的IP>:8787`，能看到面板即成功。

## 四、首次连接电视（一次性）

1. 电视开 ADB（设置→系统→系统信息，遥控器按 上 下 左 右），确保和 NAS 同一网段
2. 面板会显示「电视未连接」——首次连接触发电视弹出 RSA 授权框，遥控器选**允许**
3. 面板变成「电视已连接」后，重启一次电视，确认 ADB 开关保持、服务能自动重连
4. 之后按 README 的流程添加应用规则

也可以进容器手动预检：

```bash
docker exec -it tvguard python run.py --preflight
```

## 常见问题

**群晖 DSM 7 上 host 网络模式**
Container Manager 的 GUI 里 host 模式要在「创建容器→网络」里选；用 compose 则
`network_mode: host` 直接生效（仅 Linux 内核的 Docker 支持，NAS 都是）。
用 host 模式时**不要**再映射端口，面板地址就是 NAS IP:8787。

**不支持 host 网络的 NAS**
删掉 `network_mode: host` 那行，换成：
```yaml
    ports:
      - "8787:8787"
```
桥接模式下容器也能主动访问局域网里的电视（adb connect 是出站连接），面板走端口映射进来。

**ARM 架构 NAS（部分老群晖/树莓派）**
镜像基于 python:3.12-slim，官方有多架构版本，x86 和 ARM 都能直接构建，无需改动。

**电视 IP 变了 / 失联**
面板显示未连接时：先确认电视 ADB 开关还开着，再确认电视 IP 没变。
IP 变了就改 config.yaml 然后 `docker compose restart`。

**数据备份/迁移**
所有规则、用量、日志都在 `./data/` 目录里，整个目录拷走即完成备份。

**升级版本**
电脑上改完代码传到 NAS 覆盖，然后：
```bash
docker compose up -d --build
```

## 附：群晖 GUI 备选方案（不开 SSH）

1. Container Manager → 项目 → 新建，来源选「上传 docker-compose.yml」或指定路径
2. 项目目录设为放 tvguard 的文件夹
3. 先在 File Station 里把 config.example.yaml 复制为 config.yaml 并编辑
4. 构建并启动
5. 之后首次连接授权等同上文

> SSH 方式排查问题更方便，推荐优先用 SSH。

---

# 飞牛 fnOS 专属流程

fnOS 内置 Docker 引擎（管理面板里开启即可，不用手动安装），自带 Compose 项目管理界面，
基于 Debian，SSH 完整可用。以下两种方式任选其一。

## 方式一：图形界面（推荐，最省事）

1. **开启 Docker**：fnOS 管理面板 → 应用中心 → Docker → 开启
2. **传文件**：文件管理里建个目录，比如 `/vol1/1000/docker/tvguard`，
   把电脑上整个 tvguard 项目的文件传进去（SMB/网页上传都行）
3. **写配置**：文件管理里把 `config.example.yaml` 复制为 `config.yaml`，
   用内置文本编辑器改：`adb_host` 填电视 IP，`password` 设面板密码
4. **建 Compose 项目**：Docker → Compose → 新建项目，项目名 `tvguard`，
   路径选 `/vol1/1000/docker/tvguard`，粘贴 docker-compose.yml 内容，勾选「立即启动」
5. 浏览器打开 `http://<NAS的IP>:8787` 看到面板即成功

> 路径说明：`/vol1` 是第一个存储空间，`/vol1/1000` 里的 1000 是用户 UID，
> 在文件管理里看到自己的目录是什么就用什么。如果你喜欢 SSH，方式二更直接。

## 方式二：SSH 命令行

1. 管理面板 → 系统设置 → SSH → 打开（默认 22 端口）
2. 电脑上：`ssh 用户名@NAS的IP`，登录后 `sudo -i` 提权
3. 之后和通用流程一样：

```bash
mkdir -p /vol1/1000/docker && cd /vol1/1000/docker
# 把 tvguard 目录传到这里（scp 或 SMB 均可）
cd tvguard
cp config.example.yaml config.yaml
vi config.yaml            # 改电视 IP 和密码
docker compose up -d --build
```

## 飞牛上的三个注意点

1. **开机自启**：fnOS 断电重启后容器默认不会自动拉起。在
   Docker → 容器 → tvguard → 设置 里把**重启策略**改为「总是重启/always」
   （compose 文件里已写 `restart: unless-stopped`，用 Compose 项目创建的话一般
   会继承，但建议断电重启一次实测确认）
2. **镜像加速**：fnOS 拉取境外镜像（python:3.12-slim 基础镜像）可能很慢或失败，
   到 Docker → 设置 → 镜像加速 里配一个国内加速源（如 docker.1ms.run、
   docker.1panel.live）。构建镜像需要从 Google 下载 platform-tools，
   如 构建卡在 curl 那步，参考下面「无法访问 Google」的处理
3. **host 网络模式**：fnOS 的 Docker 原生支持 host 模式，compose 里已配好，
   无需改动。若你改用 bridge + 端口映射，adb connect 是出站连接，一样能通

### 构建镜像卡在下载 platform-tools（无法访问 Google）

Dockerfile 里从 dl.google.com 下载 adb，家里网络访问不了的话构建会失败。
处理办法：电脑上手动下载
https://dl.google.com/android/repository/platform-tools-latest-linux.zip，
放到 tvguard 目录里，然后把 Dockerfile 里的 curl 那段改为：

```dockerfile
COPY platform-tools-latest-linux.zip /tmp/pt.zip
RUN unzip -q /tmp/pt.zip -d /opt && rm /tmp/pt.zip
```

（同时删掉 apt-get 里的 curl unzip 相关行也可以）重新 `docker compose up -d --build`。

## 首次连接电视（所有 NAS 通用）

1. 电视开 ADB（雷鸟：设置→系统→系统信息，遥控器按 上 下 左 右）
2. 面板显示「电视未连接」是正常的——首次连接电视会弹 RSA 授权框，遥控器选**允许**
3. 变成「电视已连接」后，重启一次电视，确认 ADB 开关保持、能自动重连
4. 按面板流程添加应用规则；进容器手动预检：`docker exec -it tvguard python run.py --preflight`

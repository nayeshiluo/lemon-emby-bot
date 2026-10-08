# EP PR #1 审计与备份报告

日期：2026-10-08（北京时间）。

审计结论：候选源码、数据库和既有真实 Emby 验收证据一致；隔离服务的两处配置问题已修正。完整发布验收仍为 BLOCKED，PR #1 仍 Open，未合并、未部署。

## 审计结果与修正

| 项目 | 结果 | 完成位置 / 限制 |
|---|---|---|
| 候选源码 | 36 个文件的 Git blob 校验均匹配，原仓库工作区干净 | AWS 验收目录；固定提交 `918bf495f62d162b5610c3e7bc3b18d6e9c4a4d9`，本轮未修改业务代码 |
| 数据库、备份及恢复副本 | 三份 SQLite integrity_check 均为 ok；users=0、codes=2、logs=3 | AWS `data/`、`backups/`、`restore/` |
| 真实 Emby 生命周期证据 | 既有 12 项 PASS，无剩余业务测试账号 | 本轮核对证据，未重新执行全部生命周期；Telegram 输入与回复为模拟，调度任务为手动调用 |
| Emby 权限 | 已将实际 EmbyServer 进程从 UID 0 改为 UID 2 | LA 专用容器；官方镜像的监督进程仍以 root 运行 |
| 端口与隔离 | 移除全部端口映射，保留 Docker internal 网络 | LA 专用容器，无公网监听；512 MiB 内存、0.5 CPU、restart=no |
| 加固后启动 | HTTP 200，版本 4.10.1.0，原测试配置保留 | 已重新停机，SSH 隧道停止 |
| 敏感文件权限 | 验收目录 0700，配置及秘密文件 0600 | AWS 验收目录 |
| 发布门禁 | BLOCKED | 缺专用测试 Bot；真实 Telegram 投递、完整 main.py 的 Bot/调度器/Web 共享数据库运行尚未执行 |

本轮针对隔离服务配置进行了加固与启动验证，未重新运行无变更源码的整套 CI。

## 备份内容与校验

备份文件：`EP_PR1_审计脱敏备份_2026-10-08.zip`。大小 18,924 字节，共 18 个文件。

SHA-256：

```text
3b51fb9a6118fbdc16416b7cfb04c94f3ea1004649705a43d948a5bc116872d2
```

包含脱敏数据库、空密钥配置模板、源提交及 36 个文件的 Git blob 清单、隔离服务清单、初始化与验收脚本、验收证据、AUDIT.md、RESTORE.md 和逐文件 SHA-256 清单。源码通过 GitHub 固定提交恢复，包中未重复存放仓库源码。

ZIP CRC、逐文件大小及 SHA-256 校验通过；脱敏数据库 integrity_check 为 ok。已扫描实际管理 Key、管理员密码、Web secret、原兑换码及可用 Bot Token，未发现这些值进入包内。两条已消费测试兑换码替换为脱敏占位值，数据库经 VACUUM 清除旧值残留。

**此上传包用于重建隔离测试环境，不能直接恢复原 Emby 登录凭据。** 包中排除了管理 Key、Bot Token、管理员密码、实际 config.yaml 及原 Emby 认证数据库。完整私密配置备份留在 LA：

`/opt/ep-acceptance-20261008/emby-private-full-after-audit.tar.gz`（0600）。

AWS 原始数据库、配置备份仍保留于：

`/home/ubuntu/hermes-jobs/releases/ep-acceptance-20261008/backups/`。

## 恢复与后续验收顺序

1. 解压到新的私有目录，按 SHA256SUMS.json 校验文件；从 GitHub 检出上述固定提交并核对 source-manifest.json。
2. 按 service-manifest.json 使用固定镜像摘要、专用目录和 internal 网络重建 Emby；UID/GID=2，不映射端口，restart=no。不要覆盖已有服务目录。
3. 初始化新的管理员、API Key 与模板账号。恢复脱敏验收数据库并执行 integrity_check；生成新的 Web secret。
4. 配置本轮专用 Telegram Bot、测试用户/群；Bot、调度器与 Web 必须指向同一份验收数据库。脚本中原 AWS 绝对路径需保留或适配。
5. 检查 preflight 后启动完整 main.py，按验收清单执行真实 Telegram、自动调度及 Web 一致性验收，记录实际投递与数据库结果。
6. 清理测试账号，保存最终证据与数据库备份，停止测试服务。全部门禁通过后另行进行合并和部署。

详细重建命令与限制见备份包内 RESTORE.md。
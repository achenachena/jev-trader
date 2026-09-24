# 实时观察台与部署

当前提供只读网页及 SSE 实时推送。网页从真实模拟账本读取现金、可清算净值下界、
已实现/未实现盈亏、持仓、决策分数和证据、订单、逐档成交、消息源、运行状态。
两个账户各自 $1,000。空状态不填充演示盈利。UTC 日变化与本地显示时间分开。

## 本机查看

已有 bot 在运行时，只启动观察台，不要启动第二个 bot：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dashboard.txt
.venv/bin/python -m dashboard
```

打开 http://127.0.0.1:8080 。默认只监听本机，默认不启动 bot、不调用 Jev。
网页可以切换 Jev / 规则账户，展开决策阅读证据及分数，筛选拒单、判断、成交。
决策最多显示最近 80 条策略事件，订单及逐档成交各最多 100 条；不是全历史查询界面。
净值图显示最近 24 小时、每五分钟取最后一个真实估值点，较大时间缺口不连线。

## 实时推送实现

```text
bot 提交 SQLite 事务
  → 操作系统发出数据库 / WAL 文件变更通知
  → 单个 StateHub 合并约 100ms 的连续通知
  → 只读 SQLite 事务读取一致快照
  → SSE 推送给所有连接的浏览器
  → 页面更新
```

Linux 使用 watchdog 的 inotify，macOS 使用 kqueue（FSEvents 对长期打开的 WAL 可能延迟通知）。文件通知可能合并、有延迟，
也可能早于事务提交；它只提示“可能有新数据”，账本才是事实来源。每 15 秒额外
校验一次状态并更新健康信息，弥补丢失通知。这不是浏览器定时请求数据库。
账本提交到页面的延迟受文件通知、查询和网络影响，不保证毫秒级延迟。
消息源本身仍为 60 秒轮询、持仓盘口约 15 秒，网页推送不改变交易策略频率。

首连与重连都推送完整、有上限的最新快照，不依赖客户端积累 delta。事件 ID 使用
服务启动标识与单调序号；断线后的 Last-Event-ID 不触发订单重放。慢客户端只拿
最新状态，不堆无限消息。其间决策在账本中保留，但 UI 仅显示上述最近窗口。
SSE 自动重连、连接错误提示、服务端 keepalive、no-transform/no-buffer headers。
浏览器 1 秒计时器只更新“几秒前”的文案，不产生 HTTP 轮询。没有降级轮询掩盖故障。

本版为单实例、单用户观察，不引入 Redis。未来若拆分多个交易进程与多个网页服务，
可采用事务 outbox + 持久消息流 + SSE 网关；应先提交账本再发布事件，不能把内存
推送当成成交事实。页面只读，不提供交易、调参或管理资金入口。

观察台在 `dashboard/`，交易程序在 `jev_trader/`。新增网页没有改变冻结的策略实现
哈希，也没有重置现有模拟账户。SQLite `mode=ro`、query_only 和读事务防止观察台写账。
资金数值的计算保留 Decimal，前端只对显示值格式化。估值早于成交、超时、缺少深度
时明确标记未估值；不把新现金和旧持仓估值拼接。

## 推荐 Railway：一个常驻服务 + 一个持久卷

选择它是为了减少当前阶段运维，而不是声称它比所有 VPS 更便宜。
截至 2026-09-24，Hobby 每月最低 $5，含 $5 使用额，超出部分按用量结算；
模型费用另计，不能承诺总费用固定 $5。参考[费用说明](https://docs.railway.com/pricing/understanding-your-bill)。

GitHub 仓库 → Docker 构建 → 同一容器里的 paper worker + 只读网页 → 持久 SQLite。
无需另建前端平台、Postgres 或 Redis。Gateway 继续只负责 Jev 模型调用。

部署步骤：

1. Railway 新建服务，连接 `achenachena/jev-trader`，识别仓库 Dockerfile 和 railway.json。
2. **首次启动前**挂载一个持久化 Volume 到 `/app/data`。不要把运行账本放在临时文件系统。
3. 设置服务环境变量（在 Railway 控制台输入，不放 Git）：
   - `AI_GATEWAY_API_KEY`：已有 Gateway key。
   - `DASHBOARD_PASSWORD`：自行生成至少 16 位的随机密码。
   - `PAPER_DB=/app/data/paper.sqlite`
   - `PAPER_REPORTS=/app/data/reports`
   - `PORT` 由平台注入，无需手工固定。
4. 保持 **单实例、关闭 Serverless/休眠**。不配置 Cron，不使用临时 PR 环境跑同一策略。
5. 默认启动命令已包含 `--with-bot --host 0.0.0.0`。生成 HTTPS 域名，
   打开网页后通过浏览器 Basic Auth 登录：用户名 `viewer`，密码为上面的密码。
   Basic Auth 依赖平台 HTTPS；不要把对外服务放到明文 HTTP 下使用。
6. 第一次云端启动默认建立**新的独立实验账本**。本机旧账本保留，不能拼接成连续收益。
   若要保留原实验，应先停止本机 worker，通过 SQLite backup 获取一致文件，上传至
   持久卷后再启动同版本云端 worker；不要单独复制正在写入的 `.sqlite` 而漏掉 WAL。
7. 核对页面中 bot 心跳、两条源最近成功时间、8 个市场状态和 Jev 配置；验证 HTTPS 下
   SSE 未被代理缓冲、断线自动重连。公网链路尚未部署验收，不能拿本机测试代替。
8. 配置平台使用额告警及 Volume 备份。账本持续增长，应观察磁盘用量；本版不自动删除
   历史数据。后续更新交易代码或参数需要新的实验数据库，网页改动不影响策略哈希。

`/healthz` 只表示网页进程在线，不表示 bot 健康。supervisor 在 worker 退出时结束
整个服务，让平台按失败重启策略处理；活着但卡住的 worker 会在网页上显示心跳过期，
当前不自动杀死卡住的 worker。SIGTERM 转发为 worker 的 SIGINT，最多留 40 秒退出。
Railway 配置给出 50 秒退出窗口，失败最多重启 10 次，超过后须人工检查。

有持久卷的部署会有短暂停机，Railway 不支持这类服务的多副本；不要宣传零停机。
参考[Volume 限制](https://docs.railway.com/volumes/reference)。

部署配置已提供，但尚未开通付费云资源或发布公网服务。Docker 镜像需在目标平台构建
验证；本地已验证原生 Python 服务和浏览器功能。

## 后续规模扩大再考虑

单台 VPS 也能运行相同 Docker 镜像，但要自行维护 TLS、系统更新、备份与进程管理。
本版先用单服务和持久卷即可。未来需要高频盘口时再独立接入行情 WebSocket；那属于
数据源与策略实验的升级，不能只靠把浏览器传输方式换成 WebSocket 完成。

依据：[SSE / EventSource](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)、
[WHATWG SSE 标准](https://html.spec.whatwg.org/multipage/server-sent-events.html)、
[watchdog](https://pypi.org/project/watchdog/)、
[Railway 配置](https://docs.railway.com/config-as-code/reference)。

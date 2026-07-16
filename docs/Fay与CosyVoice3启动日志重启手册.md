# Fay 与 CosyVoice3 Linux 启动、日志和重启手册

本文按当前 Linux 服务器的实际目录和运行方式整理，用于日常启动、后台运行、查看日志、重启和端口冲突排查。

## 1. 当前运行信息

| 服务 | 项目目录 | Python 环境 | 主要端口 |
| --- | --- | --- | --- |
| CosyVoice3 | `/data/CosyVoice` | Conda 环境 `cosyvoice` | `50000` |
| Fay | `/data/Fay` | Miniconda `base` 环境 | `5000`、`8765`、`10001`、`10002`、`10003` |

服务调用关系：

```text
Flood Agent / 前端
        ↓
       Fay
        ↓
 CosyVoice3:50000
```

建议先启动 CosyVoice3，确认 `50000` 端口正常后，再启动 Fay。

## 2. CosyVoice3

### 2.1 前台启动

前台启动适合首次验证和排错，关闭终端后服务会停止。

```bash
conda activate cosyvoice
cd /data/CosyVoice
python runtime/python/fastapi/server.py \
  --port 50000 \
  --model_dir /data/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
```

出现以下内容表示启动成功：

```text
Application startup complete.
Uvicorn running on http://0.0.0.0:50000
```

当前 `server.py` 不接受 `--host` 参数，因此不要在命令后添加 `--host 0.0.0.0`。对外监听地址应由 `server.py` 中的 Uvicorn 启动代码设置为 `0.0.0.0`。

### 2.2 使用 tmux 后台启动

先创建独立日志目录。不要依赖当前终端保持连接。

```bash
mkdir -p /data/CosyVoice/cosylogs
touch /data/CosyVoice/cosylogs/server.log
```

后台启动：

```bash
tmux new-session -d -s cosyvoice "cd /data/CosyVoice && exec /home/sailor/miniconda3/envs/cosyvoice/bin/python runtime/python/fastapi/server.py --port 50000 --model_dir /data/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B >> /data/CosyVoice/cosylogs/server.log 2>&1"
```

这里直接使用 `cosyvoice` 环境中的 Python，不需要先执行 `conda activate cosyvoice`。

### 2.3 查看状态和日志

查看 tmux 会话：

```bash
tmux ls
```

实时查看日志：

```bash
tail -f /data/CosyVoice/cosylogs/server.log
```

退出 `tail -f`：

```text
Ctrl+C
```

查看进程：

```bash
pgrep -af 'python.*runtime/python/fastapi/server.py'
```

查看端口：

```bash
sudo ss -lntp | grep ':50000\b'
```

### 2.4 重启

先停止旧 tmux 会话：

```bash
tmux kill-session -t cosyvoice
```

确认旧进程和端口已经释放：

```bash
pgrep -af 'python.*runtime/python/fastapi/server.py'
sudo ss -lntp | grep ':50000\b'
```

然后重新后台启动：

```bash
tmux new-session -d -s cosyvoice "cd /data/CosyVoice && exec /home/sailor/miniconda3/envs/cosyvoice/bin/python runtime/python/fastapi/server.py --port 50000 --model_dir /data/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B >> /data/CosyVoice/cosylogs/server.log 2>&1"
```

最后检查日志：

```bash
tail -f /data/CosyVoice/cosylogs/server.log
```

## 3. Fay

### 3.1 前台启动

```bash
cd /data/Fay
python main.py start
```

也可以明确使用当前 Miniconda 的 Python：

```bash
cd /data/Fay
/home/sailor/miniconda3/bin/python main.py start
```

前台启动适合排错；关闭终端后服务会停止。

### 3.2 使用 tmux 后台启动

Fay 启动时会清理项目内的 `logs` 目录，因此控制台重定向日志不要写到 `/data/Fay/logs/fay-console.log`。统一使用不会被启动过程清理的 `/data/Fay/faylogs/fay.log`。

创建日志目录和日志文件：

```bash
mkdir -p /data/Fay/faylogs
touch /data/Fay/faylogs/fay.log
```

后台启动：

```bash
tmux new-session -d -s fay "cd /data/Fay && exec /home/sailor/miniconda3/bin/python main.py start >> /data/Fay/faylogs/fay.log 2>&1"
```

### 3.3 查看状态和日志

查看 tmux 会话：

```bash
tmux ls
```

实时查看 Fay 日志：

```bash
tail -f /data/Fay/faylogs/fay.log
```

查看 Fay 进程：

```bash
pgrep -af 'python.*main.py'
```

查看 Fay 端口：

```bash
sudo ss -lntp | grep -E ':(5000|8765|10001|10002|10003)\b'
```

各端口当前用途：

| 端口 | 用途 |
| --- | --- |
| `5000` | Fay HTTP 服务 |
| `8765` | MCP/SSE 服务 |
| `10001` | 音频设备 Socket |
| `10002` | 数字人播放 WebSocket |
| `10003` | WebSocket 服务 |

### 3.4 重启

停止旧 tmux 会话：

```bash
tmux kill-session -t fay
```

确认进程和端口已经释放：

```bash
pgrep -af 'python.*main.py'
sudo ss -lntp | grep -E ':(5000|8765|10001|10002|10003)\b'
```

重新后台启动：

```bash
tmux new-session -d -s fay "cd /data/Fay && exec /home/sailor/miniconda3/bin/python main.py start >> /data/Fay/faylogs/fay.log 2>&1"
```

查看启动日志：

```bash
tail -f /data/Fay/faylogs/fay.log
```

## 4. 两个服务的标准启动顺序

### 第一步：启动 CosyVoice3

```bash
tmux new-session -d -s cosyvoice "cd /data/CosyVoice && exec /home/sailor/miniconda3/envs/cosyvoice/bin/python runtime/python/fastapi/server.py --port 50000 --model_dir /data/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B >> /data/CosyVoice/cosylogs/server.log 2>&1"
```

```bash
tail -f /data/CosyVoice/cosylogs/server.log
```

看到 `Uvicorn running on http://0.0.0.0:50000` 后，按 `Ctrl+C` 退出日志查看。

### 第二步：启动 Fay

```bash
tmux new-session -d -s fay "cd /data/Fay && exec /home/sailor/miniconda3/bin/python main.py start >> /data/Fay/faylogs/fay.log 2>&1"
```

```bash
tail -f /data/Fay/faylogs/fay.log
```

### 第三步：统一检查

```bash
tmux ls
```

```bash
sudo ss -lntp | grep -E ':(50000|5000|8765|10001|10002|10003)\b'
```

## 5. 两个服务的标准重启顺序

先停止 Fay，避免它在 CosyVoice3 重启期间持续发起语音请求：

```bash
tmux kill-session -t fay
```

停止 CosyVoice3：

```bash
tmux kill-session -t cosyvoice
```

确认端口释放：

```bash
sudo ss -lntp | grep -E ':(50000|5000|8765|10001|10002|10003)\b'
```

然后按照“先 CosyVoice3、后 Fay”的顺序重新启动。

## 6. 常见问题

### 6.1 `Address already in use`

例如：

```text
OSError: [Errno 98] Address already in use
```

这通常表示 Fay 已经有一个实例在运行，又启动了第二个实例。先检查：

```bash
tmux ls
pgrep -af 'python.*main.py'
sudo ss -lntp | grep -E ':(5000|8765|10001|10002|10003)\b'
```

如果旧实例由名为 `fay` 的 tmux 会话启动，执行：

```bash
tmux kill-session -t fay
```

如果仍有明确的残留 Fay 进程，只终止查到的准确 PID：

```bash
kill <PID>
```

不要使用 `killall python`，服务器上可能还有 Agent、Ollama、MinerU 或其他 Python 服务。

### 6.2 Fay 日志文件不存在

错误示例：

```text
tail: 无法打开 '/data/Fay/logs/fay-console.log'
```

原因是 Fay 启动时清理了项目的 `logs` 目录。使用以下日志路径：

```bash
tail -f /data/Fay/faylogs/fay.log
```

### 6.3 CosyVoice3 提示不认识 `--host`

错误示例：

```text
server.py: error: unrecognized arguments: --host 0.0.0.0
```

启动命令中删除 `--host 0.0.0.0`。当前服务监听地址由 `server.py` 内部配置。

### 6.4 tmux 会话存在，但端口没有监听

依次检查会话、进程和日志：

```bash
tmux ls
pgrep -af 'python.*main.py'
pgrep -af 'python.*runtime/python/fastapi/server.py'
tail -n 100 /data/Fay/faylogs/fay.log
tail -n 100 /data/CosyVoice/cosylogs/server.log
```

tmux 会话存在并不等于程序一定启动成功；Python 进程可能已经因为配置错误或端口冲突退出。

## 7. Fay 连接 CosyVoice3 的配置检查

Fay 和 CosyVoice3 都部署在 `192.168.2.60` 同一台 Linux 服务器时，建议 Fay 内部直接使用本机地址：

```ini
cosyvoice_base_url=http://127.0.0.1:50000
cosyvoice_stream_mode=websocket
cosyvoice_ws_url=ws://127.0.0.1:50000/ws/tts
```

如果需要从其他电脑直接访问 CosyVoice3，可以使用：

```text
http://192.168.2.60:50000
ws://192.168.2.60:50000/ws/tts
```

此时 CosyVoice3 必须实际监听 `0.0.0.0:50000`，并且服务器防火墙允许访问该端口。

## 8. 日常最简检查清单

```bash
tmux ls
sudo ss -lntp | grep -E ':(50000|5000|10002)\b'
tail -n 30 /data/CosyVoice/cosylogs/server.log
tail -n 30 /data/Fay/faylogs/fay.log
```

满足以下条件即可进行 Agent 和前端播报测试：

- `cosyvoice` 和 `fay` 两个 tmux 会话都存在。
- CosyVoice3 正在监听 `50000`。
- Fay 正在监听 `5000` 和 `10002`。
- 两份日志末尾没有端口冲突、配置读取失败或 Python 异常堆栈。

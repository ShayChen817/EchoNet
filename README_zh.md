# MorvenNet（Echonet 原型）

本仓库包含一个最小可运行的分布式节点原型（Echonet / MorvenNet），演示了：

- 基于 Flask 的节点服务（`net.py`），提供分析用户命令（调用 OpenAI）、在本地或远程节点执行任务、保存任务结果等功能。
- 简单的静态前端（`frontend/`）供用户提交自然语言命令、请求 AI 拆分任务并派发到节点执行。
- 开发阶段的基于 token 的简单认证以及以内存方式保存任务结果（原型设计）。

本 README 说明如何在一台或两台机器上运行（多主机或单机模拟）、如何运行前端，以及如何进行端到端测试与排查。

---

## 快速概览

- 后端主文件：`net.py`（HTTP 服务与节点逻辑）
- 前端：`frontend/index.html`、`frontend/app.js`、`frontend/styles.css`
- 客户端示例：`client.py`
- 节点拓扑：`nodes.json`（每台机器需配置）
- 依赖清单：`requirements.txt`

## 前提条件

- 已安装 Python 3.8 及以上
- 已安装 `git`（推荐）
- 能访问 OpenAI API 的网络环境
- 在项目根目录创建 `.env`，包含有效的 `OPENAI_API_KEY`

## 环境准备（每台机器）

1. 将仓库克隆或拷贝到目标机器。
2. 创建虚拟环境并安装依赖：

```powershell
cd D:\DN
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果没有 `requirements.txt`，可直接安装所需包：

```powershell
python -m pip install flask requests openai python-dotenv
```

3. 在项目根目录创建 `.env`，填入 OpenAI Key：

```
OPENAI_API_KEY=sk-...your key...
```

4. （可选）如需接受远程调用，请设置防火墙允许 TCP 5000 入站。

---

## nodes.json（拓扑配置）

`nodes.json` 描述集群内节点以及每台机器的 `self_id/self_url`。示例：

Node A（机器 A 上的 `nodes.json`）：

```json
{
  "self_id": "nodeA",
  "self_url": "http://192.168.0.10:5000",
  "nodes": [
    {"id":"nodeA","url":"http://192.168.0.10:5000","skills":["generate_poem_en"]},
    {"id":"nodeB","url":"http://192.168.0.11:5000","skills":["translate_zh"]}
  ]
}
```

Node B（机器 B 上的 `nodes.json`）：

```json
{
  "self_id": "nodeB",
  "self_url": "http://192.168.0.11:5000",
  "nodes": [
    {"id":"nodeA","url":"http://192.168.0.10:5000","skills":["generate_poem_en"]},
    {"id":"nodeB","url":"http://192.168.0.11:5000","skills":["translate_zh"]}
  ]
}
```

确保每台机器上的 `self_id` 与 `self_url` 对应本机。

---

## 启动节点服务

在项目目录并激活 venv 后运行：

```powershell
cd D:\DN
.\.venv\Scripts\Activate.ps1
python net.py
```

Flask 服务将启动，默认监听 `127.0.0.1:5000`，根路径 `/` 会返回前端页面。

### 使用不同端口进行单机多实例模拟

将项目复制到 `instance2/` 并在不同终端分别启动两个实例（5000 / 5001）：

```powershell
# 终端1（node A）
cd D:\DN
.\.venv\Scripts\Activate.ps1
python net.py

# 终端2（node B，使用 instance2）
cd D:\DN\instance2
.\.venv\Scripts\Activate.ps1
# 若需修改端口，可编辑 net.py 或在代码中使用 PORT 环境变量
python net.py
```

（提示：若希望更方便地通过环境变量指定端口，可让我修改 `net.py` 使用 `os.getenv('PORT')`。）

---

## 前端使用

在浏览器打开 `http://<node-host>:5000/`（例如 `http://127.0.0.1:5000/`）：

- 在文本框输入自然语言命令。
- 可选输入 `User Token`（开发默认 token：`testtoken123`）。
- 点击 `Analyze` 向后端 `/analyze` 请求拆分任务（前端有 Mock 模式用于离线测试）。
- 点击 `Dispatch All` 将 pipeline 提交到 `/task`，若后端同步执行会返回并显示 `final_state`（包含 `english_poem` 和 `chinese_poem`）。

---

## API 端点简要

- `GET /` — 返回前端页面
- `GET /info` — 返回节点元信息 `{ id, url, skills }`
- `POST /analyze` — 请求体 `{ command: string }` → 返回 `{ tasks: [ { id, op, params, target_node } ] }`（调用 OpenAI 拆分）
- `POST /task` — 请求体 `{ pipeline: [ ... ] }`，需要 `X-User-Token` 头；执行 pipeline 并返回 `{ task_id, final_state }`
- `POST /execute_step` — 节点间调用接口 `{ op, params, state }` → 返回 `{ state }`
- `GET /result/<task_id>` — 获取任务结果，需拥有者 token

开发阶段使用基于 token 的简单鉴权（`X-User-Token`），默认测试 token：`testtoken123`。

---

## 命令行测试示例

1) 查看节点信息：

```powershell
.\.venv\Scripts\python.exe - <<'PY'
import requests, json
r = requests.get('http://127.0.0.1:5000/info', timeout=5)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
PY
```

2) 提交 pipeline（需 token）：

```powershell
.\.venv\Scripts\python.exe - <<'PY'
import requests, json
pipeline = [
  {"op":"generate_poem_en","params":{"prompt":"Write a short poem about autumn."}},
  {"op":"translate_zh","params":{}}
]
headers = {'X-User-Token':'testtoken123'}
r = requests.post('http://127.0.0.1:5000/task', json={'pipeline': pipeline}, headers=headers, timeout=300)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
PY
```

3) 查询结果（如异步执行）：

```powershell
.\.venv\Scripts\python.exe - <<'PY'
import requests, json
task_id = '<task_id>'
headers = {'X-User-Token':'testtoken123'}
r = requests.get(f'http://127.0.0.1:5000/result/{task_id}', headers=headers, timeout=10)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
PY
```

---

## 常见问题与排查

- `ConnectionRefusedError`：确认 `python net.py` 在运行并监听 5000 端口。
- OpenAI 相关错误：确认 `.env` 中有正确的 `OPENAI_API_KEY`，且主机能访问 `api.openai.com`。
- 若前端仍显示 Mock 日志，请取消页面上的 Mock 勾选，强制调用真实 `/analyze`。
- 若遇 401/403，请确认请求带有 `X-User-Token: testtoken123`（或 `users.json` 中的 token）。

---

## 持久化与后续改进建议

- 当前 `TASK_STORE` 为内存存储，重启会丢失。建议使用 SQLite/Redis 做持久化，我可帮助实现 SQLite 版本。
- 为节点间调用与用户鉴权引入更安全的方案（CAMP、OAuth、mTLS）。
- 将 `/analyze` 与重任务执行放入后台队列以避免 HTTP 阻塞。

---

如果你需要，我可以：
- 将 README 翻译为其它语言或调整为更简洁的操作说明；
- 修改 `net.py` 以支持 `PORT` 环境变量，便于单机运行多个实例；
- 实现 SQLite 持久化存储并演示迁移步骤。

请告诉我你想做的下一步。

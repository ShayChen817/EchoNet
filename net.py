# echonet_node.py
import json
import re
import requests
from flask import Flask, request, jsonify, send_from_directory
from openai import OpenAI
import os
from dotenv import load_dotenv
import socket
import threading
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser
import copy
import psutil
import time

# 从项目根目录的 .env 加载环境变量（不会把密钥写入源码）
load_dotenv()

# 把 frontend 目录作为静态资源目录（避免跨域，便于直接在同一服务下提供 UI）
app = Flask(__name__, static_folder='frontend', static_url_path='')


# 根路径返回前端页面 index.html，避免浏览器访问 / 时 404
@app.route('/', methods=['GET'])
def root_index():
    # Use an absolute path to be robust against different working directories
    frontend_dir = os.path.join(os.path.dirname(__file__), 'frontend')
    return send_from_directory(frontend_dir, 'index.html')

# ====== 读取配置 ======
# 尝试在脚本目录及上级目录查找 nodes.json，以避免不同工作目录导致的 FileNotFoundError
def _find_nodes_json():
    candidates = []
    script_dir = os.path.dirname(__file__)
    candidates.append(os.path.join(script_dir, 'nodes.json'))
    # parent directory
    candidates.append(os.path.join(script_dir, '..', 'nodes.json'))
    # workspace root (current working directory)
    candidates.append(os.path.join(os.getcwd(), 'nodes.json'))
    for p in candidates:
        p_norm = os.path.normpath(p)
        if os.path.exists(p_norm):
            return p_norm
    return candidates

nodes_path = _find_nodes_json()
if isinstance(nodes_path, list):
    # none found
    tried = '\n'.join([os.path.normpath(p) for p in nodes_path])
    raise RuntimeError(f"nodes.json not found. Tried:\n{tried}\n\nEnsure nodes.json exists in the project root or the EchoNet folder, or run the script from the directory containing nodes.json.")

with open(nodes_path, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

SELF_ID = CONFIG["self_id"]
SELF_URL = CONFIG["self_url"]
NODES = CONFIG["nodes"]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set in environment/.env")

# 新版 OpenAI Python 客户端
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- Minimal user store (token -> user id)
USERS = {}
if os.path.exists('users.json'):
    try:
        with open('users.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            for u in data.get('users', []):
                USERS[u['token']] = u['id']
    except Exception:
        USERS = {}
else:
    # create a default test user (convenience for local testing)
    USERS['testtoken123'] = 'user1'

# In-memory task store: task_id -> { owner_token, pipeline, final_state, status }
TASK_STORE = {}

import uuid

def _require_token(req):
    token = req.headers.get('X-User-Token') or req.args.get('token')
    if not token:
        return None, ('missing X-User-Token header', 401)
    if token not in USERS:
        return None, ('invalid token', 403)
    return token, None


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# Zeroconf globals
ZC = None
ZC_INFO = None
NODES_LOCK = threading.Lock()

# ====== 定义本节点的技能实现 ======

def skill_generate_poem_en(state, params):
    prompt = params.get("prompt", "Write a short poem about i love morven.")
    completion = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    # new client returns structure similar to legacy; access the content
    poem = completion.choices[0].message.content
    state["english_poem"] = poem
    return state

def skill_translate_zh(state, params):
    text = state.get("english_poem", "")
    prompt = params.get("prompt") or f"翻译成中文诗：\n{text}"
    completion = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    zh = completion.choices[0].message.content
    state["chinese_poem"] = zh
    return state

def skill_ai_execute(state, params):
    """Generic AI execution skill: send `instruction` or `prompt` to OpenAI and store result.

    params expected keys:
      - prompt or instruction: string to send to the model
      - output_key: where to store result in state (default 'ai_result')
      - model: optional model name
    """
    instruction = params.get('instruction') or params.get('prompt') or ''
    if not instruction:
        state.setdefault('errors', []).append('ai_execute missing prompt')
        return state
    model = params.get('model', 'gpt-4o-mini')
    try:
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": instruction}],
            temperature=params.get('temperature', 0.0),
            max_tokens=params.get('max_tokens', 512),
        )
        out = resp.choices[0].message.content
    except Exception as e:
        out = f"(openai error) {e}"
    key = params.get('output_key', 'ai_result')
    # if key already exists and is dict/list, try to append; otherwise overwrite
    if key in state and isinstance(state[key], list):
        state[key].append(out)
    else:
        state[key] = out
    return state

SKILL_IMPL = {
    "generate_poem_en": skill_generate_poem_en,
    "translate_zh": skill_translate_zh,
    "ai_execute": skill_ai_execute,
}

def self_skills():
    for n in NODES:
        if n["id"] == SELF_ID:
            return set(n["skills"])
    return set()

SELF_SKILL_SET = self_skills()

# ====== 工具：根据 op 找一个有这个技能的节点 ======
def find_node_for_op(op):
    with NODES_LOCK:
        candidates = [n for n in NODES if op in n.get("skills", [])]
    if not candidates:
        # 如果没有节点声明能执行该 op，但本地代码实现了该技能（SKILL_IMPL），
        # 则回退为在本节点本地执行，方便像 ai_execute 这样的通用技能工作。
        if op in SKILL_IMPL:
            return {"id": SELF_ID, "url": SELF_URL, "skills": list(SELF_SKILL_SET)}
        return None
    # 简单：随便选第一个，后面可以做负载均衡
    return candidates[0]

# ====== 接收完整任务（可以发给任意节点） ======
@app.route("/task", methods=["POST"])
def handle_task():
    # require user token
    token, err = _require_token(request)
    if err:
        return jsonify({'error': err[0]}), err[1]

    data = request.json or {}
    pipeline = data.get("pipeline")
    if not isinstance(pipeline, list):
        return jsonify({'error': 'pipeline missing or not a list'}), 400
    state = data.get("state", {})

    task_id = str(uuid.uuid4())
    # deep copy pipeline so we can mutate executed_by without modifying caller data
    stored_pipeline = copy.deepcopy(pipeline)
    TASK_STORE[task_id] = {'owner': token, 'pipeline': stored_pipeline, 'final_state': None, 'status': 'running'}

    for step in stored_pipeline:
        op = step["op"]
        params = step.get("params", {})

        # 如果调用方/AI 指定了 target_node 且该节点存在且声明了此技能，则优先使用
        specified = step.get("target_node")
        target_node = None
        if specified:
            for n in NODES:
                if n['id'] == specified and op in n.get('skills', []):
                    target_node = n
                    break

        # 否则按照能力选择节点
        if target_node is None:
            target_node = find_node_for_op(op)
        if target_node is None:
            return jsonify({"error": f"no node can handle op={op}"}), 400
        # 记录哪个节点将要执行这一步（或已经执行）
        step['executed_by'] = target_node['id']

        if target_node["id"] == SELF_ID:
            # 本机有这个技能 → 本地执行
            impl = SKILL_IMPL.get(op)
            if impl is None:
                return jsonify({"error": f"skill {op} not implemented on this node"}), 500
            state = impl(state, params)
        else:
            # 交给别的节点执行这一步
            url = target_node["url"].rstrip('/') + "/execute_step"
            payload = {
                "op": op,
                "params": params,
                "state": state,
            }
            try:
                resp = requests.post(url, json=payload, timeout=60)
            except Exception as e:
                return jsonify({"error": f"remote node {target_node['id']} failed to connect", "detail": str(e)}), 500
            if resp.status_code != 200:
                return jsonify({"error": f"remote node {target_node['id']} failed", "detail": resp.text}), 500
            state = resp.json()["state"]

    # 保存并返回 task_id 与最终状态
    TASK_STORE[task_id]['final_state'] = state
    TASK_STORE[task_id]['status'] = 'done'
    # 返回 pipeline（包含 executed_by 字段）以便前端显示分工
    return jsonify({"task_id": task_id, "final_state": state, "pipeline": TASK_STORE[task_id]['pipeline']})

# ====== 只执行单个 step 的接口（给别的节点调用） ======
@app.route("/execute_step", methods=["POST"])
def execute_step():
    data = request.json
    op = data["op"]
    params = data.get("params", {})
    state = data.get("state", {})

    if op not in SELF_SKILL_SET:
        return jsonify({"error": f"this node cannot handle {op}"}), 400

    impl = SKILL_IMPL.get(op)
    if impl is None:
        return jsonify({"error": f"skill {op} not implemented in code"}), 500

    state = impl(state, params)
    return jsonify({"state": state})

# ====== 查看节点信息 ======
@app.route("/info", methods=["GET"])
def info():
    return jsonify({
        "id": SELF_ID,
        "url": SELF_URL,
        "skills": list(SELF_SKILL_SET),
    })


@app.route('/result/<task_id>', methods=['GET'])
def get_result(task_id):
    # 只有任务 owner 可以读取结果
    token, err = _require_token(request)
    if err:
        return jsonify({'error': err[0]}), err[1]
    t = TASK_STORE.get(task_id)
    if not t:
        return jsonify({'error': 'task not found'}), 404
    if t['owner'] != token:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify({'task_id': task_id, 'status': t['status'], 'final_state': t.get('final_state')})


def _all_allowed_ops():
    """从 nodes.json 中收集所有声明的技能作为允许列表"""
    ops = set()
    for n in NODES:
        for s in n.get("skills", []):
            ops.add(s)
    # Always allow a generic ai execute op so model can request arbitrary AI work
    ops.add('ai_execute')
    return ops


def _extract_json_candidate(text: str):
    # 尝试直接 json.loads，否则尝试提取第一个花括号包围的 JSON
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        # 找到第一个 { 到最后一个 } 的片段
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except Exception:
                return None
        return None


def _validate_tasks_structure(obj):
    # 期望 obj 为 { "tasks": [ {id, op, params, target_node?}, ... ] }
    if not isinstance(obj, dict):
        return False, 'response is not a JSON object'
    tasks = obj.get('tasks')
    if not isinstance(tasks, list):
        return False, 'tasks must be a list'

    allowed_ops = _all_allowed_ops()
    node_ids = {n['id'] for n in NODES}

    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            return False, f'task[{i}] is not an object'
        op = t.get('op')
        if not isinstance(op, str):
            return False, f'task[{i}].op missing or not a string'
        if op not in allowed_ops:
            return False, f'task[{i}].op "{op}" not in allowed operations'
        params = t.get('params', {})
        if not isinstance(params, dict):
            return False, f'task[{i}].params must be an object'
        target = t.get('target_node')
        if target is not None and target not in node_ids:
            return False, f'task[{i}].target_node "{target}" not a known node'

    return True, ''


class DiscoveryListener:
    def add_service(self, zeroconf, service_type, name):
        info = zeroconf.get_service_info(service_type, name)
        if not info:
            return

        try:
            node_ip = socket.inet_ntoa(info.addresses[0])
        except Exception:
            node_ip = None
        try:
            node_id = info.properties.get(b"id")
            if node_id:
                node_id = node_id.decode()
        except Exception:
            node_id = None
        try:
            skills_blob = info.properties.get(b"skills")
            skills = json.loads(skills_blob.decode()) if skills_blob else []
        except Exception:
            skills = []
        # 解析可选的运行时指标（如果广播方包含这些属性）
        # 首先尝试一次性读取 'metrics' JSON blob（node_test.py 使用此格式）
        metrics_blob = info.properties.get(b"metrics")
        cpu = battery = load = health = None
        try:
            if metrics_blob:
                metrics = json.loads(metrics_blob.decode())
                cpu = metrics.get('cpu')
                battery = metrics.get('battery')
                # represent load as "current / max"
                load = f"{metrics.get('load', '?')} / {metrics.get('max_load', '?')}"
                health = metrics.get('health')
            else:
                # fallback: individual properties cpu/battery/load/health
                def _get_prop_bytes(key):
                    try:
                        b = info.properties.get(key.encode())
                        return b.decode() if b else None
                    except Exception:
                        return None

                cpu_s = _get_prop_bytes('cpu')
                battery_s = _get_prop_bytes('battery')
                load_s = _get_prop_bytes('load')
                health_s = _get_prop_bytes('health')

                try:
                    cpu = float(cpu_s) if cpu_s is not None else None
                except Exception:
                    cpu = None
                try:
                    battery = float(battery_s) if battery_s is not None else None
                except Exception:
                    battery = None
                try:
                    if load_s:
                        load = load_s.strip()
                except Exception:
                    load = None
                try:
                    health = float(health_s) if health_s is not None else None
                except Exception:
                    health = None
        except Exception:
            cpu = battery = load = health = None

        if not node_id or not node_ip:
            return

        url = f"http://{node_ip}:{info.port}"
        new_node = {"id": node_id, "url": url, "skills": skills, "cpu": cpu, "battery": battery, "load": load, "health": health}

        with NODES_LOCK:
            # replace or append
            replaced = False
            for i, n in enumerate(NODES):
                if n.get('id') == node_id:
                    NODES[i] = new_node
                    replaced = True
                    break
            if not replaced:
                NODES.append(new_node)

        # 打印更详细的发现信息
        print(f"✨ FOUND NODE → {node_id} @ {node_ip}:{info.port}\n   skills:    {skills}\n   cpu:       {cpu}%\n   battery:   {battery}\n   load:      {load}\n   health:    {health}")

    # handle updates to an existing service (e.g. metrics refreshed)
    def update_service(self, zeroconf, service_type, name):
        # on update, re-run the same logic as add_service to refresh stored node info
        try:
            self.add_service(zeroconf, service_type, name)
        except Exception:
            # be robust to transient errors
            pass

    def remove_service(self, zeroconf, service_type, name):
        print(f"💦 Node disappeared: {name}")
        # best-effort removal: service name includes id
        # we won't try to parse the name; discovery will refresh over time


def start_advertising(port):
    global ZC, ZC_INFO
    ZC = Zeroconf()
    ip = get_local_ip()
    props = {
        "id": SELF_ID,
        "skills": json.dumps(list(SELF_SKILL_SET))
    }
    info = ServiceInfo(
        "_echotest._tcp.local.",
        f"{SELF_ID}._echotest._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties=props,
        server=f"{SELF_ID}.local.",
    )
    ZC.register_service(info)
    ZC_INFO = info
    print(f"🐣 ADVERTISING: {SELF_ID} @ {ip}:{port}")

    # helper to collect local metrics
    def _get_metrics():
        try:
            cpu = psutil.cpu_percent(interval=0.1)
        except Exception:
            cpu = None
        battery = None
        try:
            bat = psutil.sensors_battery()
            battery = bat.percent if bat else None
        except Exception:
            battery = None
        # placeholder load/health values
        load = 0
        health = 1.0
        return {"cpu": cpu, "battery": battery, "load": load, "max_load": 10, "health": health}

    # start a background updater to refresh metrics on the advertised service
    def _updater():
        try:
            while True:
                time.sleep(5)
                try:
                    m = _get_metrics()
                    ZC_INFO.properties[b"metrics"] = json.dumps(m).encode('utf-8')
                    ZC.update_service(ZC_INFO)
                except Exception:
                    pass
        except Exception:
            pass

    t = threading.Thread(target=_updater, daemon=True)
    t.start()


def start_discovery():
    if ZC is None:
        # create a separate Zeroconf for browsing
        zc2 = Zeroconf()
        ServiceBrowser(zc2, "_echotest._tcp.local.", DiscoveryListener())
    else:
        ServiceBrowser(ZC, "_echotest._tcp.local.", DiscoveryListener())


@app.route('/nodes', methods=['GET'])
def nodes_list():
    with NODES_LOCK:
        # 返回每个节点的最近日志（如果存在）
        # 为安全起见只返回最近 50 条日志
        nodes_copy = []
        for n in NODES:
            nc = n.copy()
            logs = nc.get('recent_logs', [])
            nc['recent_logs'] = logs[-50:]
            nodes_copy.append(nc)
        return jsonify({'nodes': nodes_copy})


@app.route('/report_log', methods=['POST'])
def report_log():
    """接收节点发送的日志，body: { node_id: str, msg: str }"""
    data = request.json or {}
    node_id = data.get('node_id')
    msg = data.get('msg')
    if not node_id or msg is None:
        return jsonify({'error': 'node_id and msg required'}), 400

    entry = {'time': __import__('time').strftime('%H:%M:%S', __import__('time').localtime()), 'msg': msg}
    with NODES_LOCK:
        found = False
        for n in NODES:
            if n.get('id') == node_id:
                logs = n.setdefault('recent_logs', [])
                logs.append(entry)
                # keep only last 200
                if len(logs) > 200:
                    del logs[0:len(logs)-200]
                found = True
                break
        if not found:
            # create a minimal node entry so frontend can show logs
            NODES.append({'id': node_id, 'url': None, 'skills': [], 'recent_logs': [entry]})

    return jsonify({'ok': True})


@app.route('/analyze', methods=['POST'])
def analyze():
    """接受 { command: '...' }，调用 OpenAI 返回拆分任务的 JSON，验证并返回 tasks 列表"""
    data = request.json or {}
    command = data.get('command')
    if not command or not isinstance(command, str):
        return jsonify({'error': 'missing command'}), 400

    # 生成 prompt：强制模型仅返回 JSON，并且为每个 task 指定 target_node（必须是下面给出的节点 id 之一）
    allowed_ops = sorted(list(_all_allowed_ops()))
    node_ids = [n['id'] for n in NODES]
    prompt = (
        "You are an assistant that splits a user's high-level command into a sequence of small tasks.\n"
        "Return only a JSON object with the shape: { \"tasks\": [ { \"id\": string, \"op\": string, \"params\": object, \"target_node\": string }, ... ] }\n"
        "For each task, set \"target_node\" to one of the following node ids: " + ", ".join(node_ids) + ".\n"
        "You may use any operation name if a node declares that skill.\n"
        "If the work is generic AI work (not a node-specific skill), use the op name \"ai_execute\" and put an explanatory \"instruction\" or \"prompt\" string inside the task's \"params\".\n"
        "Do not invent ops that no node can perform unless you use \"ai_execute\" so the system can run it via the generic AI skill.\n"
        "Do not include any code, commands, or explanation text—only the JSON.\n"
        f"Context: nodes={json.dumps([{'id':n['id'],'skills':n.get('skills',[])} for n in NODES])}\n"
        f"User command: {command}\n"
    )

    try:
        resp = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.0,
        )
    except Exception as e:
        return jsonify({'error': 'openai error', 'detail': str(e)}), 500

    # 尝试从模型输出中提取 JSON
    text = ''
    try:
        text = resp.choices[0].message.content
    except Exception:
        # fallback: convert to str
        text = str(resp)

    parsed = _extract_json_candidate(text)
    if parsed is None:
        return jsonify({'error': 'failed to parse JSON from model output', 'raw': text}), 502

    # 如果模型没有指定 target_node 或指定了不存在的 node，后端尝试填充一个可用的节点
    tasks = parsed.get('tasks') if isinstance(parsed, dict) else None
    if not isinstance(tasks, list):
        return jsonify({'error': 'parsed output missing tasks list', 'raw': parsed}), 502

    node_ids = {n['id'] for n in NODES}
    for t in tasks:
        op = t.get('op')
        specified = t.get('target_node')
        if specified and specified in node_ids:
            # 如果指定的节点存在，且后端会在后续校验检查该节点是否支持 op
            continue
        # 需要后端填充：找一个能够执行该 op 的节点
        chosen = find_node_for_op(op)
        if chosen:
            t['target_node'] = chosen['id']
        else:
            return jsonify({'error': f'no node can handle op={op}', 'raw': parsed}), 400

    # 现在对填充后的结构做一次严格校验
    ok, reason = _validate_tasks_structure({'tasks': tasks})
    if not ok:
        return jsonify({'error': 'invalid tasks structure after fill', 'detail': reason, 'raw': tasks}), 400

    # 成功：返回解析并校验后的 tasks（包含 target_node）
    return jsonify({'tasks': tasks, 'info': 'analyze successful'})

if __name__ == "__main__":
    # 支持通过 PORT 环境变量指定端口，便于单机运行多个实例
    port = int(os.getenv('PORT', '5000'))
    try:
        start_advertising(port)
        start_discovery()
    except Exception as e:
        print('Zeroconf start failed:', e)

    try:
        app.run(host="0.0.0.0", port=port)
    finally:
        try:
            if ZC is not None and ZC_INFO is not None:
                ZC.unregister_service(ZC_INFO)
                ZC.close()
        except Exception:
            pass

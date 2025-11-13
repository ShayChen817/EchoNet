"""
Echonet 节点程序（修复版）

说明：此文件使用 openai-python >=1.0.0 的客户端接口。
把 OPENAI_API_KEY 放到环境变量或 `.env`。
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv
from openai import OpenAI

# 加载 .env（如果存在）
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("echonet")

app = Flask(__name__)

# ====== 读取配置 ======
CONFIG_PATH = "nodes.json"
if not os.path.exists(CONFIG_PATH):
    logger.error("%s not found. Please create nodes.json (see nodes.example.json).", CONFIG_PATH)
    raise SystemExit(1)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

SELF_ID = CONFIG.get("self_id")
SELF_URL = CONFIG.get("self_url")
NODES = CONFIG.get("nodes", [])

if not SELF_ID or not SELF_URL:
    logger.error("nodes.json must contain self_id and self_url fields.")
    raise SystemExit(1)

# OpenAI 客户端（支持 openai-python >=1.0.0）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set. GPT calls will fail until you set the key in env or .env file.")
    client: Optional[OpenAI] = None
else:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        client = OpenAI()


# ====== 技能实现 ======
def _call_openai_chat(prompt: str, model: str = "gpt-4o-mini") -> str:
    if not client:
        raise RuntimeError("OpenAI client not configured (OPENAI_API_KEY missing)")

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        return resp.choices[0].message.content
    except Exception:
        return getattr(resp.choices[0], "text", "")


def skill_generate_poem_en(state: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    prompt = params.get("prompt") or "Write a short, beautiful poem about the ocean at night."
    logger.info("Generating english poem with prompt: %s", prompt)
    poem = _call_openai_chat(prompt, model=params.get("model", "gpt-4o-mini"))
    s = dict(state)
    s["english_poem"] = poem
    return s


def skill_translate_zh(state: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    text = state.get("english_poem", "")
    if not text:
        raise ValueError("state missing english_poem for translate_zh")
    prompt = f"请把下面的英文诗翻译为中文诗（保留诗意）：\n\n{text}"
    logger.info("Translating english poem to Chinese")
    zh = _call_openai_chat(prompt, model=params.get("model", "gpt-4o-mini"))
    s = dict(state)
    s["chinese_poem"] = zh
    return s


SKILL_IMPL = {
    "generate_poem_en": skill_generate_poem_en,
    "translate_zh": skill_translate_zh,
}


def get_self_skills() -> set:
    for n in NODES:
        if n.get("id") == SELF_ID:
            return set(n.get("skills", []))
    return set()


SELF_SKILL_SET = get_self_skills()
logger.info("Node %s (%s) skills: %s", SELF_ID, SELF_URL, sorted(SELF_SKILL_SET))


def find_node_for_op(op: str) -> Optional[Dict[str, Any]]:
    for n in NODES:
        if op in n.get("skills", []):
            return n
    return None


@app.route("/task", methods=["POST"])
def handle_task():
    data = request.json
    if not data:
        return jsonify({"error": "missing json body"}), 400

    pipeline = data.get("pipeline")
    if not isinstance(pipeline, list):
        return jsonify({"error": "pipeline must be a list"}), 400

    state = data.get("state", {}) or {}

    for step in pipeline:
        op = step.get("op")
        params = step.get("params", {}) or {}

        if not op:
            return jsonify({"error": "step missing op"}), 400

        target_node = find_node_for_op(op)
        if target_node is None:
            return jsonify({"error": f"no node can handle op={op}"}), 400

        if target_node.get("id") == SELF_ID:
            impl = SKILL_IMPL.get(op)
            if impl is None:
                return jsonify({"error": f"skill {op} not implemented on this node"}), 500
            try:
                state = impl(state, params)
            except Exception as e:
                logger.exception("Local skill %s failed: %s", op, e)
                return jsonify({"error": "local skill failed", "detail": str(e)}), 500
        else:
            url = target_node.get("url", "").rstrip("/") + "/execute_step"
            payload = {"op": op, "params": params, "state": state}
            try:
                resp = requests.post(url, json=payload, timeout=60)
            except Exception as e:
                logger.exception("Request to %s failed: %s", url, e)
                return jsonify({"error": "remote request failed", "detail": str(e)}), 500

            if resp.status_code != 200:
                logger.error("Remote node %s returned %s: %s", target_node.get("id"), resp.status_code, resp.text)
                return jsonify({"error": "remote node failed", "detail": resp.text}), 500

            try:
                resp_json = resp.json()
            except Exception:
                return jsonify({"error": "remote node returned non-json", "detail": resp.text}), 500

            state = resp_json.get("state", {})

    return jsonify({"final_state": state})


@app.route("/execute_step", methods=["POST"])
def execute_step():
    data = request.json
    if not data:
        return jsonify({"error": "missing json body"}), 400

    op = data.get("op")
    params = data.get("params", {}) or {}
    state = data.get("state", {}) or {}

    if op not in SELF_SKILL_SET:
        return jsonify({"error": f"this node cannot handle {op}"}), 400

    impl = SKILL_IMPL.get(op)
    if impl is None:
        return jsonify({"error": f"skill {op} not implemented in code"}), 500

    try:
        state = impl(state, params)
    except Exception as e:
        logger.exception("Skill %s execution failed: %s", op, e)
        return jsonify({"error": "skill execution failed", "detail": str(e)}), 500

    return jsonify({"state": state})


@app.route("/info", methods=["GET"])
def info():
    return jsonify({
        "id": SELF_ID,
        "url": SELF_URL,
        "skills": sorted(list(SELF_SKILL_SET)),
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info("Starting Echonet node %s at %s (port=%s)", SELF_ID, SELF_URL, port)
    app.run(host="0.0.0.0", port=port)

import requests

if __name__ == "__main__":
    task = {
        "pipeline": [
            {
                "op": "generate_poem_en",
                "params": {
                    "prompt": "Write a short, beautiful poem about my lover morven."
                }
            },
            {
                "op": "translate_zh",
                "params": {}
            }
        ],
        "state": {}
    }

    # 修改为任意一个节点 URL（nodeA 或 nodeB）
    target = "http://127.0.0.1:5000/task"
    print("Sending task to", target)
    resp = requests.post(target, json=task, timeout=120)
    print(resp.status_code)
    print(resp.text)

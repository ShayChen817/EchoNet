# MorvenNet (Echonet Prototype)

This repository contains a minimal distributed node prototype (Echonet / MorvenNet) that demonstrates:

- A Flask-based node service (`net.py`) which exposes APIs to analyze user commands (via OpenAI), execute tasks locally or on remote nodes, and store task results.
- A small static frontend (`frontend/`) that lets a user submit a natural-language command, request AI task splitting, and dispatch tasks to nodes.
- A simple token-based user check (development-only) and an in-memory task store.

This README documents how to set up one or two nodes (multi-host or single-machine simulation), how to run the frontend, and how to test the end-to-end flow.

---

## Quick overview

- Main backend file: `net.py` (HTTP server and node logic)
- Frontend: `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`
- Example client helper: `client.py`
- Node topology: `nodes.json` (update this on each node)
- Requirements: `requirements.txt`

## Prerequisites

- Python 3.8+ installed
- `git` (recommended)
- Internet access for OpenAI API calls
- A valid OpenAI API key (set in `.env` as `OPENAI_API_KEY`)

## Prepare environment (on each machine)

1. Clone or copy the repository to the machine.
2. Create a virtual environment and install dependencies:

```powershell
cd D:\DN
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you don't have `requirements.txt`, install the required packages directly:

```powershell
python -m pip install flask requests openai python-dotenv
```

3. Create a `.env` file in the project root containing your OpenAI API key:

```
OPENAI_API_KEY=sk-...your key...
```

4. (Optional) Ensure firewall allows incoming TCP 5000 if you will accept remote calls.

---

## nodes.json (topology)

`nodes.json` describes the nodes and `self_id/self_url` for each machine. Example formats:

Node A (`nodes.json` on machine A):

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

Node B (`nodes.json` on machine B):

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

Make sure `self_id` and `self_url` on each host match that host's identity and network address.

---

## Running the node service

Start the service (in the project directory, with the venv activated):

```powershell
cd D:\DN
.\.venv\Scripts\Activate.ps1
python net.py
```

The Flask server will start and (if reachable) listen on `127.0.0.1:5000` and the machine address. The root (`/`) serves the frontend.

### Using a different port (single‑machine multi‑instance)

To run a second instance on the same machine, copy the project into `instance2/` (already included) and start the second instance in a separate terminal. Set `PORT` environment variable if you prefer to run on a different port.

Example for two terminals:

```powershell
# Terminal 1 (node A)
cd D:\DN
.\.venv\Scripts\Activate.ps1
# $env:PORT=5000
python net.py

# Terminal 2 (node B using instance2 folder)
cd D:\DN\instance2
.\.venv\Scripts\Activate.ps1
# $env:PORT=5001
python net.py
```

(Note: `net.py` currently runs on port 5000 by default. If you want explicit `PORT` handling, edit `net.py` to use `os.getenv('PORT')`).

---

## Frontend usage

Open a browser to `http://<node-host>:5000/` (e.g. `http://127.0.0.1:5000/`).

- Enter a natural‑language command in the text box.
- Optionally provide a `User Token` (`testtoken123` by default in this prototype).
- Click `Analyze` to ask the back-end `/analyze` API to split the command into tasks. (The front-end also supports a mock mode for offline testing.)
- Click `Dispatch All` to submit the pipeline to `/task`. If the backend runs the steps synchronously it returns `final_state`. The front-end will display `english_poem` and `chinese_poem` if present.

---

## API endpoints

- `GET /` — serves frontend `index.html`
- `GET /info` — returns node metadata: `{ id, url, skills }`
- `POST /analyze` — body `{ command: string }` → returns `{ tasks: [ { id, op, params, target_node } ] }`; uses OpenAI to split commands
- `POST /task` — body `{ pipeline: [ {op, params, target_node?} ] }`, requires `X-User-Token` header; executes pipeline and returns `{ task_id, final_state }`
- `POST /execute_step` — used by other nodes to ask this node to execute a single op: `{ op, params, state }` → returns `{ state }`
- `GET /result/<task_id>` — returns `{ task_id, status, final_state }`, requires the owner token

Authentication: minimal token check `X-User-Token` in headers (development only). Default test token: `testtoken123`.

---

## Testing the flow (command line)

1. Check node info:

```powershell
.\.venv\Scripts\python.exe - <<'PY'
import requests, json
r = requests.get('http://127.0.0.1:5000/info', timeout=5)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
PY
```

2. Submit a pipeline (requires token):

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

If the pipeline includes steps assigned to remote nodes, the node will forward the step to the `target_node`'s `/execute_step` endpoint.

3. Query result later (if asynchronous):

```powershell
.\.venv\Scripts\python.exe - <<'PY'
import requests, json
task_id = '<task_id_from_previous>'
headers = {'X-User-Token':'testtoken123'}
r = requests.get(f'http://127.0.0.1:5000/result/{task_id}', headers=headers, timeout=10)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
PY
```

---

## Troubleshooting

- `ConnectionRefusedError` when calling `http://127.0.0.1:5000` — ensure `python net.py` is running and that the process is listening on port 5000.
- `openai` errors — ensure `.env` contains a valid `OPENAI_API_KEY` and that the host can reach `api.openai.com`.
- If front-end shows `Mock` logs, disable the mock checkbox to call the real `/analyze` endpoint.
- If you get `401/403` from `/task` or `/result`, include header `X-User-Token: testtoken123` (or a token in `users.json`).

---

## Persistence & Next steps (suggestions)

- The current `TASK_STORE` is in-memory. For production use, persist tasks to SQLite/Redis. I can help implement a simple SQLite store.
- Add stronger authentication (CAMP, OAuth, or mTLS) for node-to-node calls.
- Move `/analyze` to background job if you want asynchronous analyze or to avoid long blocking HTTP calls.

---

If you want, I can also:
- Add `README.md` sections in Chinese or other languages.
- Modify `net.py` to respect `PORT` env var for easier multi‑instance runs on one machine.
- Implement SQLite persistence for `TASK_STORE`.

Ask which of the above you'd like me to do next.

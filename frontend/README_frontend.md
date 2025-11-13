Echonet 前端原型

目的
- 提供一个简单的静态前端，用于向后端提交自然语言命令或上传命令文件，调用 AI 拆分逻辑，将命令分解为若干子任务，并展示子任务结果与"派发"按钮。

文件
- `index.html` — 主页面
- `app.js` — 前端逻辑（对 `/analyze` 发起 POST 请求，解析返回的 `tasks`；可 mock）
- `styles.css` — 简单样式

后端契约（建议）

1) /analyze  - 将用户命令拆分为子任务
- 方法：POST
- 请求 Content-Type: application/json
- 请求体：{ "command": "...用户命令文本..." }
- 响应示例：
  {
    "tasks": [
      { "id": "t1", "op": "generate_poem_en", "params": {"prompt": "..."}, "target_node": "nodeA" },
      { "id": "t2", "op": "translate_zh", "params": {"text_var": "english_poem"}, "target_node": "nodeB" }
    ],
    "info": "可选元信息"
  }

2) /task - 派发或直接执行单个任务（与现有节点 API 保持兼容）
- 方法：POST
- 请求体：{ "op": "generate_poem_en", "params": {...}, "state": {...} }
- 响应：{ "ok": true, "state": {...} }

运行前端（本地）
- 使用任何静态文件服务器或直接把文件夹作为 Flask 的 static 文件夹。
- 简单快速本地查看（PowerShell）:

  # 在 D:\DN\frontend 目录下
  python -m http.server 8000
  # 浏览器打开 http://localhost:8000

或把前端交由后端 Flask 服务提供（推荐用于本地开发，避免 CORS）：

1) 确保 `net.py` 服务启动（它已经配置将 `frontend/` 作为静态目录）
2) 在浏览器打开 http://127.0.0.1:5000

前端增加了一个 `User Token` 输入框，后端实现了一个最小的 token 校验机制：
- 默认本地测试 token: `testtoken123`（对应用户 id `user1`）
- 在生产中请替换为真实认证/身份系统（比如 CAMP）

安全与注意事项
- 前端默认启用 mock 模式（`app.js` 的 mockToggle 默认启用），以便在后端尚未实现时测试 UI。
- 后端在实现 `/analyze` 时，应加入鉴权、输入长度限制以及对生成的任务的白名单检查，避免任意代码或命令注入。

后续
- 将前端派发按钮接入后端 `/task`，并展示执行结果和错误。
- 为多节点调度，实现 `/analyze` 返回包含目标节点和执行顺序的计划。
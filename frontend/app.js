// 简单前端逻辑：发送 /analyze 请求并显示拆分的子任务；若后端不可用，可使用 mock 数据

const analyzeBtn = document.getElementById('analyzeBtn');
const dispatchAllBtn = document.getElementById('dispatchAllBtn');
const commandEl = document.getElementById('command');
const tokenEl = document.getElementById('token');
const fileInput = document.getElementById('fileUpload');
const subtasksEl = document.getElementById('subtasks');
const logArea = document.getElementById('logArea');
const mockToggle = document.getElementById('mockToggle');
const nodesListEl = document.createElement('div');
nodesListEl.id = 'nodesList';
const container = document.querySelector('.container');
container.insertBefore(nodesListEl, document.getElementById('result'));

// Chat elements
const messagesEl = document.getElementById('messages');
const chatInput = document.getElementById('chatInput');
const chatSend = document.getElementById('chatSend');

function log(msg) {
  const t = new Date().toLocaleTimeString();
  logArea.textContent += `[${t}] ${msg}\n`;
  logArea.scrollTop = logArea.scrollHeight;
}

async function readFileText() {
  const f = fileInput.files[0];
  if (!f) return null;
  return await f.text();
}

// 页面加载时请求 /nodes 并显示
async function refreshNodes() {
  try {
    const r = await fetch('/nodes');
    if (!r.ok) throw new Error('failed to fetch nodes');
    const js = await r.json();
    renderNodes(js.nodes || []);
  } catch (e) {
    nodesListEl.textContent = '无法获取节点列表（后端可能不可用）';
  }
}

function renderNodes(nodes) {
  nodesListEl.innerHTML = '<h2>集群节点</h2>';
  const ul = document.createElement('ul');
  nodes.forEach(n => {
    const li = document.createElement('li');
    li.textContent = `${n.id} — ${n.url} — skills: ${ (n.skills||[]).join(',') }`;
    ul.appendChild(li);
  });
  nodesListEl.appendChild(ul);
  // 同时创建/刷新节点卡片（清空并为每个节点创建 container）
  const cardRoot = document.getElementById('nodeCards');
  cardRoot.innerHTML = '';
  nodes.forEach((n, idx) => {
    const card = document.createElement('div');
    card.className = 'node-card';
    card.id = `nodecard-${n.id}`;
    const label = String.fromCharCode(65 + idx); // A, B, C, ...
    const cpuText = n.cpu !== undefined && n.cpu !== null ? `${n.cpu}%` : 'n/a';
    const batteryText = n.battery !== undefined && n.battery !== null ? `${n.battery}` : 'n/a';
    const loadText = n.load !== undefined && n.load !== null ? `${n.load}` : 'n/a';
    const healthText = n.health !== undefined && n.health !== null ? `${(n.health*100).toFixed(0)}%` : 'n/a';
    card.innerHTML = `
      <h3>${label} (${n.id})</h3>
      <div class="meta">${n.url}</div>
      <div class="meta metrics">CPU: ${cpuText} • Battery: ${batteryText} • Load: ${loadText} • Health: ${healthText}</div>
      <div class="meta status"><span class="online-badge ${n.url? 'online':'offline'}">${n.url? '在线':'离线'}</span> <span id="last-${n.id}" class="last-update">最后更新：${new Date().toLocaleTimeString()}</span></div>
      <div class="tasks" id="tasks-${n.id}"></div>
      <div class="node-logs" id="logs-${n.id}"><h4>实时日志</h4></div>
    `;
    cardRoot.appendChild(card);
  });
}

function renderNodeLogs(nodes) {
  nodes.forEach(n => {
    const container = document.getElementById(`logs-${n.id}`);
    if (!container) return;
    // 清空现有日志显示（保留标题）
    const header = container.querySelector('h4');
    container.innerHTML = header ? header.outerHTML : '<h4>实时日志</h4>';
    const logs = n.recent_logs || [];
    logs.slice().reverse().forEach(l => {
      const el = document.createElement('div');
      el.className = 'node-log-item';
      el.innerHTML = `<div class="log-time">${escapeHtml(l.time)}</div><div class="log-msg">${escapeHtml(l.msg)}</div>`;
      container.appendChild(el);
    });
  });
}

analyzeBtn.addEventListener('click', async () => {
  subtasksEl.innerHTML = '';
  const fileText = await readFileText();
  const command = (fileText && fileText.trim()) || commandEl.value.trim();
  if (!command) { alert('请先输入命令或上传文件'); return; }
  // ensure at least one node is online
  if (!currentNodes || currentNodes.length === 0) {
    alert('No nodes are currently online. Please wait for nodes to appear before analyzing.');
    return;
  }

  log('Analyzing command...');
  try {
    const useMock = mockToggle.checked;
    let respJson;
    if (useMock) {
      log('Using mock response (frontend simulation)');
      respJson = mockAnalyze(command);
      await new Promise(r => setTimeout(r, 500));
    } else {
      const token = tokenEl.value.trim();
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['X-User-Token'] = token;
      const r = await fetch('/analyze', {
        method: 'POST',
        headers,
        body: JSON.stringify({ command }),
      });
      if (!r.ok) throw new Error(`分析接口返回 ${r.status}`);
      respJson = await r.json();
    }

    renderSubtasks(respJson);
    log('分析完成');
    dispatchAllBtn.disabled = false;
  } catch (err) {
    log('Analyze failed: ' + err);
    alert('Analyze failed: ' + err);
  }
});

function renderSubtasks(data) {
  // 期望 data = { tasks: [ { id, op, params, target_node (可选) } ], info?: '' }
  subtasksEl.innerHTML = '';
  if (!data || !Array.isArray(data.tasks)) {
    subtasksEl.textContent = 'No subtasks detected (data.tasks empty)';
    return;
  }

  data.tasks.forEach((t, idx) => {
    const card = document.createElement('div');
    card.className = 'task-card';
    // 保存原始任务对象，便于后续提交保留 target_node 等字段
    card.dataset.task = JSON.stringify(t);
    card.innerHTML = `
      <div class="task-header">任务 ${idx+1} — ${t.op} <span class="small">(目标：${t.target_node||'本地'})</span></div>
      <div class="task-body"><pre>${escapeHtml(JSON.stringify(t.params, null, 2))}</pre></div>
      <div class="task-actions">
        <button class="dispatch-single">派发</button>
        <span class="status">待处理</span>
      </div>
    `;
    const dispatchBtn = card.querySelector('.dispatch-single');
    const statusSpan = card.querySelector('.status');
    dispatchBtn.addEventListener('click', async () => {
      statusSpan.textContent = '派发中...';
      try {
        const useMock = mockToggle.checked;
        let result;
        if (useMock) {
          log(`Mock dispatch ${t.op}`);
          await new Promise(r=>setTimeout(r,700));
          result = { ok: true, result: { mock: 'ok', op:t.op } };
        } else {
          // 这里按后端约定调用 /task
          const token = tokenEl.value.trim();
          const headers = { 'Content-Type': 'application/json' };
          if (token) headers['X-User-Token'] = token;
          // submit as a single-step pipeline
          const r = await fetch('/task', {
              method: 'POST',
              headers,
              body: JSON.stringify({ pipeline: [{ op: t.op, params: t.params || {}, target_node: t.target_node }] }),
            });
          const js = await r.json();
          if (!r.ok) throw new Error(JSON.stringify(js));
          result = js;
        }
          statusSpan.textContent = 'Completed';
        log(`Task ${t.op} completed: ${JSON.stringify(result)}`);
      } catch (err) {
        statusSpan.textContent = 'Failed';
        log('Dispatch failed: ' + err);
      }
    });

    subtasksEl.appendChild(card);
  });
}

function appendMessage(role, text) {
  const el = document.createElement('div');
  el.className = 'message ' + (role === 'user' ? 'user' : 'assistant');
  el.textContent = text;
  // ensure messagesEl exists (page might not have chat in older versions)
  const msgs = document.getElementById('messages') || messagesEl;
  if (msgs) {
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
  }
}

function formatFinalState(final_state) {
  if (!final_state) return '（无返回）';
  if (final_state.ai_result && final_state.ai_result.output) return final_state.ai_result.output;
  // If poem fields present, render readable text
  const en = final_state.english_poem;
  const zh = final_state.chinese_poem;
  if ((typeof en === 'string' && en.trim()) || (typeof zh === 'string' && zh.trim())) {
    let out = '';
    if (en && en.trim()) {
      out += 'English:\n' + en.trim() + '\n\n';
    }
    if (zh && zh.trim()) {
      out += '中文:\n' + zh.trim();
    }
    return out.trim();
  }

  // If small object, render key: value lines
  if (typeof final_state === 'object') {
    const keys = Object.keys(final_state);
    if (keys.length > 0 && keys.length <= 10) {
      return keys.map(k => `${k}: ${JSON.stringify(final_state[k])}`).join('\n');
    }
    return JSON.stringify(final_state, null, 2);
  }
  return String(final_state);
}

chatSend && chatSend.addEventListener('click', async () => {
  const msg = (chatInput && chatInput.value || '').trim();
  if (!msg) return;
  const token = tokenEl.value.trim();
  if (!token) { alert('请先填写 User Token（例如 testtoken123）以便提交请求'); return; }

  appendMessage('user', msg);
  chatInput.value = '';

  // send as ai_execute pipeline to /task
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['X-User-Token'] = token;
    const r = await fetch('/task', {
      method: 'POST',
      headers,
      body: JSON.stringify({ pipeline: [{ op: 'ai_execute', params: { prompt: msg } }] })
    });
    const js = await r.json();
    if (!r.ok) throw new Error(JSON.stringify(js));

    // format final_state into readable assistant text
    const reply = formatFinalState(js.final_state);
    appendMessage('assistant', reply);

    // show task assignment in logs / node cards if pipeline present
    if (js.pipeline && Array.isArray(js.pipeline)) {
      js.pipeline.forEach((step, i) => {
        const exec = step.executed_by || step.target_node || 'unknown';
        addTaskToNode(exec, { op: step.op, params: step.params || {}, time: new Date().toLocaleTimeString() });
      });
    }
  } catch (err) {
    appendMessage('assistant', '请求失败：' + String(err));
  }
});

// send on Enter
chatInput && chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    chatSend.click();
  }
});

// 提交整个 pipeline 给后端 /task（一次性）
dispatchAllBtn.addEventListener('click', async () => {
  const tasks = Array.from(document.querySelectorAll('.task-card')).map((card, idx) => {
    // 优先使用当初 AI 返回并保存在 data-task 的完整任务对象（包含 target_node）
    try {
      const t = JSON.parse(card.dataset.task || '{}');
      return { op: t.op, params: t.params || {}, target_node: t.target_node };
    } catch(e) {
      // 兜底：从 DOM 恢复
      const opText = card.querySelector('.task-header').textContent || '';
      const pre = card.querySelector('.task-body pre').textContent;
      let params = {};
      try { params = JSON.parse(pre); } catch(e) { params = {}; }
      const op = opText.split('—')[1] ? opText.split('—')[1].trim().split(' ')[0] : `op${idx}`;
      return { op, params };
    }
  });

  if (!tasks.length) { alert('没有子任务可提交'); return; }
  const token = tokenEl.value.trim();
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['X-User-Token'] = token;

  log('提交 pipeline 给后端 /task');
  try {
    const r = await fetch('/task', { method: 'POST', headers, body: JSON.stringify({ pipeline: tasks }) });
    const js = await r.json();
    if (!r.ok) throw new Error(JSON.stringify(js));
    log('Submit successful, task_id=' + js.task_id);
    alert('Submit successful, task_id=' + js.task_id);
    // 显示 final_state（如果后端同步返回）
    if (js.final_state) {
      // 如果页面存在聊天框，则把 final_state 的 ai_result 输出显示为助手回复
      const msgs = document.getElementById('messages');
      if (msgs) {
        // format final_state into readable assistant text
        const reply = formatFinalState(js.final_state);
        appendMessage('assistant', reply);
      } else {
        // 兼容旧版页面：仅在元素存在时设置
        const enEl = document.getElementById('englishPoem');
        const zhEl = document.getElementById('chinesePoem');
        if (enEl) enEl.textContent = js.final_state.english_poem || '(无)';
        if (zhEl) zhEl.textContent = js.final_state.chinese_poem || '(无)';
        log('final_state 已显示在页面');
      }
    }
    // 如果后端返回 pipeline（包含 executed_by），显示执行分工
    if (js.pipeline && Array.isArray(js.pipeline)) {
      js.pipeline.forEach((step, i) => {
        log(`Step ${i+1}: op=${step.op} target=${step.target_node || 'N/A'} executed_by=${step.executed_by || 'unknown'}`);
        // add to node card
        const exec = step.executed_by || step.target_node || 'unknown';
        addTaskToNode(exec, { op: step.op, params: step.params || {}, time: new Date().toLocaleTimeString() });
      });
    }
  } catch (err) {
    log('Submit failed: ' + err);
    alert('Submit failed: ' + err);
  }
});


function addTaskToNode(nodeId, task) {
  const container = document.getElementById(`tasks-${nodeId}`);
  if (!container) {
    // node card not present — append to logs
    log(`收到节点 ${nodeId} 的任务，但未找到卡片，任务：${JSON.stringify(task)}`);
    return;
  }
  const el = document.createElement('div');
  el.className = 'task-item';
  el.innerHTML = `<div class="task-op">${escapeHtml(task.op)}</div><div class="task-time">${escapeHtml(task.time)}</div><pre>${escapeHtml(JSON.stringify(task.params || {}, null, 2))}</pre>`;
  container.insertBefore(el, container.firstChild);
}

function mockAnalyze(command) {
  // 返回示例结构：两个任务：生成英文诗（本地 nodeA），翻译成中文（nodeB）
  return {
    tasks: [
      {
        id: 't1',
        op: 'generate_poem_en',
        params: { prompt: `Generate an English poem about: ${command}` },
        target_node: 'nodeA'
      },
      {
        id: 't2',
        op: 'translate_zh',
        params: { text_var: 'english_poem' },
          target_node: 'nodeB'
      }
    ],
    info: 'mock拆分：生成英文诗 -> 翻译中文'
  };
}

function escapeHtml(s) {
  return s.replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'})[c]);
}

// 自动填充示例
commandEl.value = 'Generate a short poem about autumn and translate it into Chinese';
log('Frontend ready');
// Attempt to fetch and show current nodes
let currentNodes = [];
refreshNodes();
// Poll nodes and logs every 3s
setInterval(async () => {
  try {
    const r = await fetch('/nodes');
    if (!r.ok) return;
    const js = await r.json();
    currentNodes = js.nodes || [];
    renderNodes(currentNodes);
    renderNodeLogs(currentNodes);
    // enable/disable analyze depending on whether we have online nodes
    const anyOnline = (currentNodes || []).length > 0;
    analyzeBtn.disabled = !anyOnline;
  } catch (e) {
    // ignore polling errors
  }
}, 3000);

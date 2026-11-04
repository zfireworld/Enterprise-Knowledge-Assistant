const state = { history: [], documents: [], busy: false };
const byId = id => document.getElementById(id);
const el = (tag, className, text) => { const node = document.createElement(tag); node.className = className; node.textContent = text; return node; };

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || `请求失败 (${response.status})`);
  return result;
}

function switchView(view) {
  document.querySelectorAll('.view').forEach(node => node.classList.add('hidden'));
  byId(`${view}-view`).classList.remove('hidden');
  document.querySelectorAll('.nav-item').forEach(node => node.classList.toggle('active', node.dataset.view === view));
  byId('breadcrumb').textContent = view === 'chat' ? '知识问答' : '知识资料';
  if (view === 'documents') refreshDocuments();
}

function showTrace(result) {
  const steps = result.trace || [];
  if (!steps.length && !result.citation_problems?.length && !result.query_rewrite) return null;
  const details = el('details', 'trace-details', '');
  details.append(el('summary', '', '查看执行过程'));
  if (result.query_rewrite?.status === 'completed') {
    details.append(el('div', 'trace-line', `问题改写：${result.query_rewrite.rewritten}`));
  } else if (result.query_rewrite?.status === 'failed') {
    details.append(el('div', 'trace-line', '问题改写失败，已使用原问题继续。'));
  }
  for (const [index, step] of steps.entries()) {
    const line = el('div', 'trace-line', `${index + 1}. ${step.action || '未知步骤'}`);
    if (step.arguments) line.append(el('div', '', `参数：${JSON.stringify(step.arguments)}`));
    if (step.reason) line.append(el('div', '', `依据：${step.reason}`));
    if (step.error) line.append(el('div', 'trace-error', `错误：${step.error}`));
    else if (Array.isArray(step.result)) line.append(el('div', '', `结果：${step.result.length} 条`));
    else if (step.result?.doc_id) line.append(el('div', '', `已读取：${step.result.doc_id} / ${step.result.chunk_id}`));
    else if (typeof step.result === 'string') line.append(el('div', '', `结果：${step.result}`));
    details.append(line);
  }
  for (const problem of result.citation_problems || []) {
    details.append(el('div', 'trace-line trace-error', `引用问题：${problem.doc_id} / ${problem.chunk_id}：${problem.reason}`));
  }
  return details;
}

function showMessage(role, content, result) {
  byId('welcome').classList.add('hidden');
  const row = el('div', `message ${role}`, '');
  if (role === 'assistant') row.append(el('span', 'message-icon', '✳'));
  const bubble = el('div', 'bubble', '');
  if (result) {
    const labels = { completed: '已完成', needs_clarification: '需要确认', insufficient: '资料不足', incomplete: '未完成' };
    bubble.append(el('div', 'answer-status', labels[result.status] || result.status));
  }
  bubble.append(el('div', 'message-text', content));
  for (const citation of result?.citations || []) {
    const source = el('div', 'citation', '');
    source.append(el('strong', '', `▤  ${citation.doc_id} · ${citation.version_date}`));
    source.append(el('span', '', `“${citation.quote}”`));
    if (citation.source_url && citation.source_url.startsWith('/api/documents/')) {
      const link = el('a', 'source-link', citation.page_number ? `查看原文 · 第 ${citation.page_number} 页 ↗` : '查看原文件 ↗');
      link.href = citation.source_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      source.append(link);
    }
    bubble.append(source);
  }
  if (result?.missing_information) bubble.append(el('div', 'citation', `待补充：${result.missing_information}`));
  if (result) {
    const trace = showTrace(result);
    if (trace) bubble.append(trace);
  }
  row.append(bubble);
  byId('conversation').append(row);
  byId('conversation').scrollTop = byId('conversation').scrollHeight;
  return row;
}

async function streamQuestion(payload, loading) {
  const response = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `请求失败 (${response.status})`);
  }
  if (!response.body) throw new Error('浏览器不支持流式响应');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', finalResult;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        const lines = frame.split('\n'), type = lines.find(line => line.startsWith('event: '))?.slice(7);
        const data = lines.filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n');
        if (!type || !data) continue;
        const event = JSON.parse(data);
        if (type === 'progress') loading.querySelector('.message-text').textContent = event.message;
        if (type === 'failure') throw new Error(event.message || '问答执行失败');
        if (type === 'final') finalResult = event;
      }
      if (finalResult) return finalResult;
    }
    throw new Error('连接已结束，未收到最终结果');
  } finally { await reader.cancel(); }
}

async function sendQuestion(question) {
  if (state.busy || !question.trim()) return;
  state.busy = true;
  const send = document.querySelector('.send-button');
  send.disabled = true;
  showMessage('user', question);
  const loading = showMessage('assistant', '正在检索知识资料…');
  try {
    const result = await streamQuestion({ question, history: state.history.slice(-20), model: byId('model-select').value }, loading);
    loading.remove();
    showMessage('assistant', result.answer || '暂时无法生成回答。', result);
    state.history.push({ role: 'user', content: question }, { role: 'assistant', content: result.answer || '' });
  } catch (error) {
    loading.remove();
    showMessage('assistant', `请求未完成：${error.message}`);
  } finally { state.busy = false; send.disabled = false; }
}

function renderDocuments() {
  const docs = state.documents;
  byId('doc-count').replaceChildren(document.createTextNode(`${docs.length} `), el('small', '', '份资料'));
  byId('nav-count').textContent = docs.length;
  byId('summary-count').textContent = `${docs.length} 份资料`;
  byId('list-count').textContent = `共 ${docs.length} 份`;
  const recent = byId('recent-docs'); recent.replaceChildren();
  for (const doc of docs.slice(-3).reverse()) {
    const item = el('div', 'recent-item', ''); const info = el('div', '', '');
    item.append(el('span', 'file-icon', '▤'));
    info.append(el('strong', '', doc.title), el('small', '', doc.version_date));
    item.append(info); recent.append(item);
  }
  if (!docs.length) recent.append(el('p', 'answer-status', '暂无资料'));
  const body = byId('documents-body'); body.replaceChildren();
  for (const doc of docs) {
    const row = document.createElement('tr');
    for (const value of [doc.title, doc.doc_id, `V${doc.version_number || 1} · ${doc.version_date}`, `${doc.chunks} 个`, '● 可检索']) row.append(el('td', '', value));
    const actions = el('div', 'document-actions', '');
    const update = el('button', 'text-button', '更新版本'); update.addEventListener('click', () => openImport(doc.doc_id));
    const history = el('button', 'text-button', '版本历史'); history.addEventListener('click', () => showVersions(doc.doc_id));
    actions.append(update, history); row.firstChild.append(actions);
    body.append(row);
  }
  byId('empty-docs').classList.toggle('hidden', docs.length > 0);
}

async function refreshDocuments() {
  const indicator = document.querySelector('.connection');
  try {
    state.documents = await request('/api/documents');
    renderDocuments();
    indicator.innerHTML = '<i></i>知识库已连接';
  } catch (error) {
    indicator.textContent = '知识库未连接';
    byId('recent-docs').replaceChildren(el('p', 'answer-status', error.message));
    byId('empty-docs').textContent = `无法读取资料：${error.message}`;
    byId('empty-docs').classList.remove('hidden');
  }
}

function openImport(docId = '') {
  byId('import-form').reset();
  const select = byId('target-doc');
  select.replaceChildren(new Option('新建文档（V1）', ''));
  for (const doc of state.documents) select.add(new Option(`更新：${doc.title}（当前 V${doc.version_number || 1}）`, doc.doc_id));
  select.value = docId;
  const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  byId('version-date').value = now.toISOString().slice(0, 10);
  byId('file-label').textContent = '点击选择或拖拽文件到这里';
  byId('import-feedback').textContent = '';
  byId('import-feedback').classList.remove('error');
  byId('import-dialog').showModal();
}

async function showVersions(docId) {
  const dialog = byId('history-dialog'), list = byId('history-list');
  list.replaceChildren(el('p', 'answer-status', '正在读取版本…'));
  dialog.showModal();
  try {
    const data = await request(`/api/documents/${encodeURIComponent(docId)}/versions`);
    byId('history-title').textContent = `${data.title} · 版本历史`;
    list.replaceChildren();
    for (const version of [...data.versions].reverse()) {
      const row = el('div', 'history-row', '');
      const label = version.version_id === data.current_version ? '当前版本' : ({published: '历史版本', processing: '处理中', failed: '导入失败'}[version.status] || version.status);
      row.append(el('strong', '', `V${version.number} · ${label}`));
      row.append(el('small', '', `${version.version_date} · ${version.chunks || 0} 个片段`));
      if (version.error) row.append(el('small', 'import-feedback error', version.error));
      list.append(row);
    }
  } catch (error) { list.replaceChildren(el('p', 'import-feedback error', error.message)); }
}

function watchImport(id) {
  return new Promise((resolve, reject) => {
    const base = `/api/import/${encodeURIComponent(id)}`;
    let source, retries = 0, settled = false, reconnectTimer;
    const finish = (error, task) => {
      if (settled) return;
      settled = true; source?.close(); clearTimeout(timeout); clearTimeout(reconnectTimer);
      if (error) reject(error); else resolve(task);
    };
    const timeout = setTimeout(() => finish(new Error('等待进度超时，任务可能仍在后台运行')), 30 * 60 * 1000);
    const handleTask = task => {
      if (task.status === 'completed') return finish(null, task);
      if (task.status === 'failed') return finish(new Error(task.error || '导入失败'));
      byId('import-feedback').textContent = `${task.step || '正在处理文档'}${task.chunks ? `（${task.chunks} 个片段）` : ''}，请稍候…`;
    };
    const connect = () => {
      if (settled) return;
      source = new EventSource(`${base}/events`);
      source.addEventListener('progress', event => {
        try { handleTask(JSON.parse(event.data)); }
        catch (_) { finish(new Error('导入进度数据无效')); }
      });
      source.addEventListener('missing', () => finish(new Error('任务不存在或服务已重启')));
      source.onerror = async () => {
        source.close();
        try {
          const task = await request(base);
          handleTask(task);
          if (settled) return;
          if (++retries > 3) return finish(new Error('进度连接中断，任务可能仍在后台运行'));
          byId('import-feedback').textContent = '进度连接中断，正在重新连接…';
          reconnectTimer = setTimeout(connect, 2000);
        } catch (error) { finish(error); }
      };
    };
    connect();
  });
}

document.querySelectorAll('[data-view]').forEach(node => node.addEventListener('click', () => switchView(node.dataset.view)));
document.querySelectorAll('[data-prompt]').forEach(node => node.addEventListener('click', () => sendQuestion(node.dataset.prompt)));
byId('chat-form').addEventListener('submit', event => { event.preventDefault(); const field = byId('question'); const text = field.value.trim(); if (text) { field.value = ''; sendQuestion(text); } });
byId('question').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); byId('chat-form').requestSubmit(); } });
byId('new-chat').addEventListener('click', () => { if (state.busy) return; state.history = []; document.querySelectorAll('.message').forEach(node => node.remove()); byId('welcome').classList.remove('hidden'); });
for (const id of ['open-import', 'open-import-side']) byId(id).addEventListener('click', () => openImport());
byId('close-history').addEventListener('click', () => byId('history-dialog').close());
for (const id of ['close-import', 'cancel-import']) byId(id).addEventListener('click', () => { if (!byId('submit-import').disabled) byId('import-dialog').close(); });
byId('import-dialog').addEventListener('cancel', event => { if (byId('submit-import').disabled) event.preventDefault(); });
byId('file-input').addEventListener('change', event => { byId('file-label').textContent = event.target.files[0]?.name || '点击选择或拖拽文件到这里'; });
const dropzone = byId('dropzone');
for (const type of ['dragenter', 'dragover']) dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add('dragging'); });
for (const type of ['dragleave', 'drop']) dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.remove('dragging'); });
dropzone.addEventListener('drop', event => { if (event.dataTransfer.files.length) { byId('file-input').files = event.dataTransfer.files; byId('file-input').dispatchEvent(new Event('change')); } });
byId('import-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = byId('submit-import'), feedback = byId('import-feedback');
  const form = new FormData(); form.append('file', byId('file-input').files[0]); form.append('version_date', byId('version-date').value);
  if (byId('target-doc').value) form.append('doc_id', byId('target-doc').value);
  button.disabled = true; feedback.classList.remove('error'); feedback.textContent = '正在上传文件…';
  try {
    const task = await request('/api/import', { method: 'POST', body: form });
    const result = await watchImport(task.id);
    feedback.textContent = `V${result.version_number} 导入成功：${result.chunks} 个片段。`;
    await refreshDocuments();
    setTimeout(() => byId('import-dialog').close(), 800);
  } catch (error) { feedback.classList.add('error'); feedback.textContent = `导入未完成或状态无法确认：${error.message}`; }
  finally { button.disabled = false; }
});
refreshDocuments();

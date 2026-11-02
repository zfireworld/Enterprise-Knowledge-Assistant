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
    bubble.append(source);
  }
  if (result?.missing_information) bubble.append(el('div', 'citation', `待补充：${result.missing_information}`));
  row.append(bubble);
  byId('conversation').append(row);
  byId('conversation').scrollTop = byId('conversation').scrollHeight;
  return row;
}

async function sendQuestion(question) {
  if (state.busy || !question.trim()) return;
  state.busy = true;
  const send = document.querySelector('.send-button');
  send.disabled = true;
  showMessage('user', question);
  const loading = showMessage('assistant', '正在检索知识资料…');
  try {
    const result = await request('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history: state.history.slice(-20), model: byId('model-select').value }) });
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
    for (const value of [doc.title, doc.doc_id, doc.version_date, `${doc.chunks} 个`, '● 可检索']) row.append(el('td', '', value));
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

function openImport() {
  byId('import-form').reset();
  const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  byId('version-date').value = now.toISOString().slice(0, 10);
  byId('file-label').textContent = '点击选择或拖拽文件到这里';
  byId('import-feedback').textContent = '';
  byId('import-feedback').classList.remove('error');
  byId('import-dialog').showModal();
}

async function pollImport(id) {
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    const task = await request(`/api/import/${encodeURIComponent(id)}`);
    if (task.status === 'completed') return task;
    if (task.status === 'failed') throw new Error(task.error || '导入失败');
    byId('import-feedback').textContent = '正在解析文档并建立向量索引，请稍候…';
  }
}

document.querySelectorAll('[data-view]').forEach(node => node.addEventListener('click', () => switchView(node.dataset.view)));
document.querySelectorAll('[data-prompt]').forEach(node => node.addEventListener('click', () => sendQuestion(node.dataset.prompt)));
byId('chat-form').addEventListener('submit', event => { event.preventDefault(); const field = byId('question'); const text = field.value.trim(); if (text) { field.value = ''; sendQuestion(text); } });
byId('question').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); byId('chat-form').requestSubmit(); } });
byId('new-chat').addEventListener('click', () => { if (state.busy) return; state.history = []; document.querySelectorAll('.message').forEach(node => node.remove()); byId('welcome').classList.remove('hidden'); });
for (const id of ['open-import', 'open-import-side']) byId(id).addEventListener('click', openImport);
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
  button.disabled = true; feedback.classList.remove('error'); feedback.textContent = '正在上传文件…';
  try {
    const task = await request('/api/import', { method: 'POST', body: form });
    const result = await pollImport(task.id);
    feedback.textContent = `导入成功：${result.chunks} 个片段。`;
    await refreshDocuments();
    setTimeout(() => byId('import-dialog').close(), 800);
  } catch (error) { feedback.classList.add('error'); feedback.textContent = `导入失败：${error.message}`; }
  finally { button.disabled = false; }
});
refreshDocuments();

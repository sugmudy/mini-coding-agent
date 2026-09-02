const state = { records: [], subject: '全部' };
const els = {
  totalCount: document.getElementById('totalCount'),
  totalMinutes: document.getElementById('totalMinutes'),
  completionRate: document.getElementById('completionRate'),
  subjectFilter: document.getElementById('subjectFilter'),
  recordList: document.getElementById('recordList'),
  recordForm: document.getElementById('recordForm'),
  printBtn: document.getElementById('printBtn'),
  template: document.getElementById('recordTemplate'),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.status === 204 ? null : response.json();
}

function normalizedSubject(subject) {
  return subject.trim();
}

function subjects() {
  const values = new Set(state.records.map((r) => normalizedSubject(r.subject)));
  return ['全部', ...values];
}

function metrics(records) {
  const totalCount = records.length;
  const totalMinutes = records.reduce((sum, item) => sum + item.minutes, 0);
  const completedCount = records.filter((item) => item.completed).length;
  const completionRate = totalCount ? Math.round((completedCount / totalCount) * 100) : 0;
  return { totalCount, totalMinutes, completionRate };
}

function renderEmptyState() {
  const empty = document.createElement('article');
  empty.className = 'card empty-state';
  empty.innerHTML = '<h2>暂无匹配的学习记录</h2><p>尝试切换筛选条件，或新增一个科目记录。</p>';
  els.recordList.appendChild(empty);
}

function render() {
  const filtered = state.subject === '全部' ? state.records : state.records.filter((r) => normalizedSubject(r.subject) === state.subject);
  const { totalCount, totalMinutes, completionRate } = metrics(filtered);
  els.totalCount.textContent = totalCount;
  els.totalMinutes.textContent = totalMinutes;
  els.completionRate.textContent = `${completionRate}%`;
  els.subjectFilter.innerHTML = subjects().map((item) => `<option value="${item}" ${item === state.subject ? 'selected' : ''}>${item}</option>`).join('');
  els.recordList.innerHTML = '';
  if (!filtered.length) {
    renderEmptyState();
    return;
  }
  filtered.forEach((record) => {
    const node = els.template.content.cloneNode(true);
    node.querySelector('.subject').textContent = record.subject;
    node.querySelector('.badge').textContent = record.completed ? '已完成' : '进行中';
    node.querySelector('.minutes').textContent = `${record.minutes} 分钟`;
    node.querySelector('.record-id').textContent = `ID: ${record.id}`;
    const toggleBtn = node.querySelector('.toggle-btn');
    toggleBtn.textContent = record.completed ? '标记为未完成' : '标记为已完成';
    toggleBtn.classList.toggle('completed', record.completed);
    toggleBtn.addEventListener('click', async () => {
      await api(`/api/records/${record.id}`, { method: 'PATCH', body: JSON.stringify({ completed: !record.completed }) });
      await load();
    });
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'delete-btn';
    deleteBtn.textContent = '删除';
    deleteBtn.addEventListener('click', async () => {
      if (!window.confirm(`确认删除 ${record.subject} 这条学习记录吗？`)) return;
      await api(`/api/records/${record.id}`, { method: 'DELETE' });
      await load();
    });
    node.querySelector('.record-actions').appendChild(deleteBtn);
    els.recordList.appendChild(node);
  });
}

async function load() {
  state.records = await api('/api/records');
  const availableSubjects = subjects();
  if (!availableSubjects.includes(state.subject)) state.subject = '全部';
  render();
}

els.subjectFilter.addEventListener('change', (event) => {
  state.subject = event.target.value;
  render();
});

els.recordForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(els.recordForm);
  await api('/api/records', {
    method: 'POST',
    body: JSON.stringify({ subject: data.get('subject'), minutes: Number(data.get('minutes')), completed: false }),
  });
  els.recordForm.reset();
  await load();
});

els.printBtn.addEventListener('click', () => window.print());
load();

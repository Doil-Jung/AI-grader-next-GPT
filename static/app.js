// ═══ 전역 상태 ═══
let currentProject = null;
let eventSource = null;
let submissionData = [];

// ═══ 탭 전환 ═══
function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const el = document.getElementById('tab-' + name);
  if (el) el.classList.add('active');
  document.querySelectorAll(`.tab[data-tab="${name}"]`).forEach(t => t.classList.add('active'));
  if (name === 'results') { loadRounds('resultRound', () => loadResults()); loadRoundsForAnalysis(); }
  if (name === 'submission') loadRounds('subRound', () => loadSubmission());
  if (name === 'materials') scanMaterials();
  if (name === 'grading') renderGradingGrid();
}

// ═══ 모달 ═══
function openModal(id) { document.getElementById(id).classList.add('show'); }
function closeModal(id) { document.getElementById(id).classList.remove('show'); }

// ═══ 프로젝트 관리 ═══
async function loadProjects() {
  const res = await fetch('/api/projects');
  const list = await res.json();
  const el = document.getElementById('projectList');
  if (!list.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">📁</div><p>프로젝트가 없습니다</p></div>';
    return;
  }
  el.innerHTML = list.map(p => `
    <div class="project-card ${currentProject?.id === p.id ? 'active' : ''}" onclick="selectProject('${p.id}')">
      <h3>${esc(p.name)}</h3>
      <div class="meta">
        <span>📏 ${p.criteria_count}개 항목</span>
        <span>📊 ${p.round_count}회차</span>
        <span>👥 ${p.team_count}${p.project_type === 'exam' ? '명' : '팀'}</span>
      </div>
      <div class="meta" style="margin-top:4px"><span>${p.project_type === 'exam' ? '📝 서술형 시험' : '📄 보고서 평가'}</span><span>🤖 ${esc(p.ai_provider || 'gemini_api')}</span></div>
      <div style="margin-top:8px;text-align:right">
        <button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteProject('${p.id}')">삭제</button>
      </div>
    </div>
  `).join('');
}

async function selectProject(id, skipTabSwitch) {
  const res = await fetch(`/api/projects/${id}`);
  currentProject = await res.json();
  document.getElementById('headerProject').textContent = currentProject.name;
  localStorage.setItem('lastProjectId', id);
  await populateSettings();
  if (!skipTabSwitch) showTab('settings');
  loadProjects();
}

function openNewProjectModal() { openModal('newProjectModal'); document.getElementById('newProjName').value = ''; document.getElementById('newProjDesc').value = ''; }

async function createProject() {
  const name = document.getElementById('newProjName').value.trim();
  if (!name) return alert('이름을 입력하세요');
  const res = await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, description: document.getElementById('newProjDesc').value, project_type: document.getElementById('newProjType').value }) });
  const data = await res.json();
  closeModal('newProjectModal');
  await selectProject(data.id);
  loadProjects();
}

async function deleteProject(id) {
  if (!confirm('정말 삭제하시겠습니까?')) return;
  await fetch(`/api/projects/${id}`, { method: 'DELETE' });
  if (currentProject?.id === id) { currentProject = null; document.getElementById('headerProject').textContent = '프로젝트를 선택하세요'; }
  loadProjects();
}

// ═══ 설정 ═══
async function loadModels(provider = 'gemini_api', preferredModel = '') {
  const res = await fetch(`/api/models?provider=${encodeURIComponent(provider)}`);
  const models = await res.json();
  const sel = document.getElementById('cfgModel');
  sel.innerHTML = Object.entries(models).map(([k, v]) => `<option value="${k}">${v.name} - ${v.description}</option>`).join('');
  if (preferredModel && [...sel.options].some(option => option.value === preferredModel)) {
    sel.value = preferredModel;
  }
  return sel.value;
}

async function loadProviders() {
  const res = await fetch('/api/providers');
  const providers = await res.json();
  const sel = document.getElementById('cfgProvider');
  sel.innerHTML = providers.map(p => `<option value="${p.id}" ${p.disabled ? 'disabled' : ''}>${esc(p.name)}${p.stable || p.disabled ? '' : ' - 실험 기능'}</option>`).join('');
}

async function populateSettings() {
  if (!currentProject) return;
  document.getElementById('cfgName').value = currentProject.name || '';
  document.getElementById('cfgDesc').value = currentProject.description || '';
  document.getElementById('cfgProjectType').value = currentProject.project_type || 'report';
  document.getElementById('cfgProvider').value = currentProject.ai_provider || 'gemini_api';
  document.getElementById('cfgTemp').value = currentProject.temperature ?? 0.2;
  document.getElementById('cfgPrompt').value = currentProject.prompt_template || '';
  // Materials
  const m = currentProject.materials || {};
  document.getElementById('matSource').value = m.source_type || 'folder';
  document.getElementById('matFolder').value = m.folder_path || '';
  document.getElementById('matTypes').value = (m.file_types || ['pdf', 'mp4']).join(',');
  document.getElementById('matPattern').value = m.naming_pattern || '(\\d+)\\.\\s*(.+)';
  toggleMatSource();
  renderRubric();
  renderExamSettings();
  updateProjectModeUI();
  await updateProviderUI();
}

function changeProjectType(value) {
  if (!currentProject || !['report', 'exam'].includes(value)) return;
  if (currentProject.project_type !== value) {
    currentProject.project_type = value;
    currentProject.prompt_template = '';
    document.getElementById('cfgPrompt').value = '';
  }
  updateProjectModeUI();
}

function updateProjectModeUI() {
  const isExam = currentProject?.project_type === 'exam';
  document.getElementById('examTabButton').style.display = isExam ? '' : 'none';
  document.getElementById('submissionTabButton').style.display = isExam ? 'none' : '';
  document.getElementById('reportRubricCard').style.display = isExam ? 'none' : '';
  document.getElementById('reportPromptCard').style.display = isExam ? 'none' : '';
  document.getElementById('examIntegratedMaterialsCard').style.display = isExam ? '' : 'none';
  document.getElementById('thApproval').style.display = isExam ? '' : 'none';
}

async function updateProviderUI() {
  const provider = document.getElementById('cfgProvider')?.value || currentProject?.ai_provider || 'gemini_api';
  const preferred = currentProject?.ai_provider === provider ? currentProject.ai_model : '';
  await loadModels(provider, preferred);

}

function renderRubric() {
  const el = document.getElementById('rubricEditor');
  const cats = currentProject?.categories || [];
  el.innerHTML = cats.map((cat, ci) => `
    <div class="card" style="background:var(--surface2)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <input value="${esc(cat.name)}" placeholder="영역명" style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-weight:600;font-size:.95rem" onchange="currentProject.categories[${ci}].name=this.value">
        <button class="btn-icon" onclick="currentProject.categories.splice(${ci},1);renderRubric()">🗑</button>
      </div>
      <div id="criteria-${ci}">
        ${cat.criteria.map((c, i) => renderCriterionItem(ci, i, c)).join('')}
      </div>
      <button class="btn btn-secondary btn-sm" onclick="addCriterion(${ci})" style="margin-top:8px">+ 항목 추가</button>
    </div>
  `).join('');
}

function renderCriterionItem(ci, i, c) {
  return `<div class="criterion-item">
    <div class="row" style="margin-bottom:8px">
      <input value="${esc(c.id)}" placeholder="ID" style="max-width:100px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:.85rem" onchange="currentProject.categories[${ci}].criteria[${i}].id=this.value">
      <input value="${esc(c.name)}" placeholder="항목명" style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:.85rem" onchange="currentProject.categories[${ci}].criteria[${i}].name=this.value">
      <button class="btn-icon" onclick="currentProject.categories[${ci}].criteria.splice(${i},1);renderRubric()">✕</button>
    </div>
    <div class="row">
      <input value="${esc(c.description)}" placeholder="설명" style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:.85rem;flex:2" onchange="currentProject.categories[${ci}].criteria[${i}].description=this.value">
      <input value="${c.scale?.join(',') || '5,4,3,2,1'}" placeholder="척도(콤마)" style="max-width:140px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:.85rem" onchange="currentProject.categories[${ci}].criteria[${i}].scale=this.value.split(',').map(Number)">
    </div>
  </div>`;
}

function addCategory() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  if (!currentProject.categories) currentProject.categories = [];
  currentProject.categories.push({ name: '새 영역', criteria: [] });
  renderRubric();
}

function addCriterion(ci) {
  const cats = currentProject.categories;
  // 모든 카테고리의 기존 ID에서 최대 번호를 찾아 +1 (충돌 방지)
  let maxNum = 0;
  for (const cat of cats) {
    for (const c of cat.criteria) {
      const m = c.id?.match(/^c(\d+)$/);
      if (m) maxNum = Math.max(maxNum, parseInt(m[1]));
    }
  }
  const id = 'c' + (maxNum + 1);
  cats[ci].criteria.push({ id, name: '새 항목', description: '새 항목 설명', scale: [5, 4, 3, 2, 1], scale_labels: ['매우우수', '우수', '보통', '미흡', '매우미흡'] });
  renderRubric();
}

async function saveSettings() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  currentProject.name = document.getElementById('cfgName').value;
  currentProject.description = document.getElementById('cfgDesc').value;
  currentProject.project_type = document.getElementById('cfgProjectType').value;
  currentProject.ai_model = document.getElementById('cfgModel').value;
  currentProject.ai_provider = document.getElementById('cfgProvider').value;
  currentProject.temperature = parseFloat(document.getElementById('cfgTemp').value);
  currentProject.prompt_template = document.getElementById('cfgPrompt').value;
  if (currentProject.project_type === 'exam' && currentProject.exam) {
    currentProject.exam.additional_instructions = document.getElementById('examAdditionalInstructions')?.value.trim() || '';
    currentProject.exam.grading_mode = document.getElementById('examGradingMode')?.value || currentProject.exam.grading_mode || 'strict';
    currentProject.exam.source_mode = document.getElementById('examSourceMode')?.value || 'auto';
    currentProject.exam.expected_question_count = Math.max(0, parseInt(document.getElementById('examExpectedQuestionCount')?.value) || 0);
  }
  const res = await fetch(`/api/projects/${currentProject.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(currentProject) });
  if (!res.ok) { const err = await res.json(); return alert(err.error || '저장 실패'); }
  currentProject = await res.json();
  await populateSettings();
  alert('설정이 저장되었습니다');
  loadProjects();
}


async function regeneratePrompt() {
  if (!currentProject) return;
  // 현재 루브릭 상태를 먼저 저장
  collectRubricFromEditor();
  await fetch(`/api/projects/${currentProject.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ categories: currentProject.categories }),
  });
  const res = await fetch(`/api/projects/${currentProject.id}/generate-prompt`, { method: 'POST' });
  const data = await res.json();
  document.getElementById('cfgPrompt').value = data.prompt;
  currentProject.prompt_template = data.prompt;
}

// 루브릭 에디터는 onchange로 currentProject.categories를 직접 업데이트하므로
// 별도 수집 불필요. 이 함수는 호환성을 위해 유지.
function collectRubricFromEditor() {
  // currentProject.categories는 이미 최신 상태
}

// ═══ 서술형 시험 설정 ═══
function renderExamSettings() {
  if (!currentProject) return;
  if (!currentProject.exam) currentProject.exam = { questions: [], students: [], scan_split: {} };
  const students = currentProject.exam.students || [];
  document.getElementById('examStudents').value = students.map(s => `${s.number}, ${s.name || ''}`).join('\n');
  const split = currentProject.exam.scan_split || {};
  document.getElementById('examStartPage').value = split.start_page || 1;
  document.getElementById('examPagesPerStudent').value = split.pages_per_student || 0;
  document.getElementById('examBoundaries').value = (split.boundaries || []).join(',');
  document.getElementById('examScanStatus').textContent = split.source_path ? `저장됨: ${split.source_path.split(/[\\/]/).pop()}` : '';
  document.getElementById('examAdditionalInstructions').value = currentProject.exam.additional_instructions || '';
  const modeSelect = document.getElementById('examGradingMode');
  if (modeSelect) modeSelect.value = currentProject.exam.grading_mode || 'strict';
  document.getElementById('examSourceMode').value = currentProject.exam.source_mode || 'auto';
  document.getElementById('examExpectedQuestionCount').value = currentProject.exam.expected_question_count || 0;
  document.getElementById('examSourceStatus').textContent = currentProject.exam.rubric_source_path
    ? `✅ 공식 기준표 적용됨: ${currentProject.exam.rubric_source_path.split(/[\\/]/).pop()}`
    : '';
  renderExamQuestions();
}

function renderExamQuestions() {
  const el = document.getElementById('examQuestionEditor');
  const questions = currentProject?.exam?.questions || [];
  if (!questions.length) {
    el.innerHTML = '<div class="empty-state"><p>문제지를 업로드하여 기준을 생성하거나 문항을 직접 추가하세요.</p></div>';
    return;
  }
  el.innerHTML = questions.map((q, index) => {
    const elementText = (q.scoring_elements || []).map(e => `${e.points}|${e.required === false ? '선택' : '필수'}|${e.description}`).join('\n');
    const points = (q.scoring_elements || []).reduce((sum, e) => sum + Number(e.points || 0), 0);
    const pointColor = points > Number(q.max_score || 0) ? 'var(--danger)' : 'var(--text2)';
    return `<div class="card" style="background:var(--surface2)">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
        <input value="${esc(q.number)}" style="max-width:80px" aria-label="문항 번호" onchange="updateExamQuestion(${index},'number',this.value)">
        <input type="number" min="1" value="${q.max_score || 1}" style="max-width:100px" aria-label="배점" onchange="updateExamQuestion(${index},'max_score',this.value)">
        <span style="font-size:.8rem;color:${pointColor}">부분점 합 ${points}/${q.max_score || 1}</span>
        <button class="btn-icon" style="margin-left:auto" onclick="removeExamQuestion(${index})">🗑</button>
      </div>
      <div class="form-group"><label>문제</label><textarea rows="2" onchange="updateExamQuestion(${index},'question_text',this.value)">${esc(q.question_text || '')}</textarea></div>
      <div class="form-group"><label>모범 답안</label><textarea rows="3" onchange="updateExamQuestion(${index},'model_answer',this.value)">${esc(q.model_answer || '')}</textarea></div>
      <div class="form-group"><label>부분점 요소 - 한 줄에 점수|필수/선택|기준</label><textarea rows="4" onchange="updateExamElements(${index},this.value)">${esc(elementText)}</textarea></div>
      <div class="form-row">
        <div class="form-group"><label>허용 답안 - 줄바꿈 구분</label><textarea rows="2" onchange="updateExamList(${index},'accepted_answers',this.value)">${esc((q.accepted_answers || []).join('\n'))}</textarea></div>
        <div class="form-group"><label>주요 감점 사례 - 줄바꿈 구분</label><textarea rows="2" onchange="updateExamList(${index},'common_errors',this.value)">${esc((q.common_errors || []).join('\n'))}</textarea></div>
      </div>
      <div class="form-group"><label>🗜 핵심 확인 요소 (AI 채점용, 핵심 기준 채점 방식에서 사용) - 줄바꿈 구분</label><textarea rows="2" onchange="updateExamList(${index},'core_criteria',this.value)">${esc((q.core_criteria || []).join('\n'))}</textarea></div>
    </div>`;
  }).join('');
}

function updateExamQuestion(index, field, value) {
  const q = currentProject.exam.questions[index];
  q[field] = field === 'max_score' ? Math.max(1, parseInt(value) || 1) : value;
  if (field === 'max_score') renderExamQuestions();
}

function updateExamElements(index, value) {
  currentProject.exam.questions[index].scoring_elements = value.split(/\r?\n/).map(line => {
    const parts = line.split('|');
    return { points: Math.max(0, parseInt(parts[0]) || 0), required: (parts[1] || '필수').trim() !== '선택', description: parts.slice(2).join('|').trim() };
  }).filter(e => e.points > 0 && e.description);
  renderExamQuestions();
}

function updateExamList(index, field, value) {
  currentProject.exam.questions[index][field] = value.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
}

function addExamQuestion() {
  if (!currentProject?.exam) return;
  const index = currentProject.exam.questions.length + 1;
  currentProject.exam.questions.push({ id: `q${index}`, number: String(index), question_text: '', max_score: 5, model_answer: '', scoring_elements: [], accepted_answers: [], common_errors: [] });
  renderExamQuestions();
}

function removeExamQuestion(index) {
  currentProject.exam.questions.splice(index, 1);
  renderExamQuestions();
}

let rubricSynthesisDraft = null;

async function synthesizeRubricFromResults() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  const status = document.getElementById('rubricSynthesisStatus');
  const preview = document.getElementById('rubricSynthesisPreview');
  document.getElementById('applySynthesisBtn').style.display = 'none';
  preview.innerHTML = '';
  status.textContent = '⏳ 전체 채점 결과를 종합하는 중... (1~2분)';
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/exam/synthesize-rubric`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '종합 실패');
    rubricSynthesisDraft = data;
    preview.innerHTML = data.questions.map(q => `<div class="card" style="background:var(--surface2)">
      <strong>${esc(q.number)}번 (배점 ${q.max_score}점)</strong>
      <p style="margin:6px 0"><strong>예시답안:</strong> ${esc(q.model_answer || '-')}</p>
      <p style="margin:6px 0 2px"><strong>부분점 기준안:</strong></p>
      <ul style="margin:0 0 6px 18px">${(q.scoring_elements || []).map(e =>
        `<li>${e.points}점 (${e.required === false ? '선택' : '필수'}) - ${esc(e.description)}</li>`).join('') || '<li>-</li>'}</ul>
      <p style="margin:6px 0"><strong>정답 인정 답안:</strong> ${esc((q.accepted_answers || []).join(' / ') || '-')}</p>
      <p style="margin:6px 0"><strong>감점·오답 사례:</strong> ${esc((q.common_errors || []).join(' / ') || '-')}</p>
      ${q.rationale ? `<p style="margin:6px 0;color:var(--text2);font-size:.85rem">종합 근거: ${esc(q.rationale)}</p>` : ''}
    </div>`).join('');
    document.getElementById('applySynthesisBtn').style.display = '';
    status.textContent = `✅ ${data.round_id}회차 학생 ${data.student_count}명 결과 종합 완료 - 검토 후 반영하세요.`;
  } catch (e) { status.textContent = `❌ ${e.message}`; }
}

function applyRubricSynthesis() {
  if (!rubricSynthesisDraft || !currentProject?.exam) return;
  const byNumber = {};
  for (const d of rubricSynthesisDraft.questions) byNumber[String(d.number).trim()] = d;
  for (const q of currentProject.exam.questions) {
    const d = byNumber[String(q.number).trim()];
    if (!d) continue;
    if (d.model_answer) q.model_answer = d.model_answer;
    if ((d.scoring_elements || []).length) q.scoring_elements = d.scoring_elements;
    if ((d.accepted_answers || []).length) q.accepted_answers = d.accepted_answers;
    if ((d.common_errors || []).length) q.common_errors = d.common_errors;
  }
  renderExamQuestions();
  document.getElementById('rubricSynthesisStatus').textContent =
    '✅ 문항 설정에 반영됨 - 위에서 내용을 검토한 뒤 "문항 저장"을 누르세요.';
}

function updateExamGradingMode(value) {
  if (!currentProject?.exam) return;
  currentProject.exam.grading_mode = value;
  const status = document.getElementById('examModeStatus');
  if (status) status.textContent = '"문항 저장"을 누르면 적용됩니다.';
}

async function compressCriteria() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  const status = document.getElementById('examModeStatus');
  status.textContent = '⏳ 상세 기준을 핵심 확인 요소로 압축 중...';
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/exam/compress-criteria`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '압축 실패');
    currentProject.exam.questions = data.questions;
    currentProject.prompt_template = data.prompt_template;
    renderExamQuestions();
    const modeNote = data.grading_mode === 'core' ? '' : ' 채점에 쓰려면 방식을 "핵심 기준 채점"으로 바꾸세요.';
    status.textContent = `✅ ${data.updated}문항 압축 완료 - 각 문항의 핵심 확인 요소를 검토하세요.${modeNote}`;
  } catch (e) { status.textContent = `❌ ${e.message}`; }
}

async function examRubricFromText() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  const text = document.getElementById('examRubricTextInput').value.trim();
  const status = document.getElementById('examRubricTextStatus');
  if (!text) { status.textContent = '지시 텍스트를 입력하세요.'; return; }
  const hadQuestions = (currentProject.exam?.questions || []).length > 0;
  status.textContent = hadQuestions ? '⏳ 지시를 반영해 문항 수정 중...' : '⏳ 문항 초안 생성 중...';
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/exam/rubric/from-text`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '문항 생성·수정 실패');
    currentProject.exam.questions = data.questions;
    currentProject.prompt_template = data.prompt_template;
    renderExamQuestions();
    document.getElementById('examRubricTextInput').value = '';
    status.textContent = `✅ ${data.questions.length}문항 ${data.mode === 'revise' ? '수정' : '생성'} 완료 - 아래에서 검토하세요. (이미 저장됨)`;
  } catch (e) { status.textContent = `❌ ${e.message}`; }
}

async function uploadExamSources() {
  if (!currentProject) return;
  const question = document.getElementById('examQuestionFile').files[0];
  const rubric = document.getElementById('examRubricFile').files[0];
  if (!question && !rubric) {
    alert('문제지 또는 채점기준표를 선택하세요.');
    return false;
  }
  const fd = new FormData();
  if (question) fd.append('question_file', question);
  if (rubric) fd.append('rubric_file', rubric);
  const status = document.getElementById('examSourceStatus');
  status.textContent = '⏳ 파일 저장 중...';
  const res = await fetch(`/api/projects/${currentProject.id}/exam/sources`, { method: 'POST', body: fd });
  const data = await res.json();
  if (!res.ok) { status.textContent = `❌ ${data.error}`; return false; }
  if (data.question_source_path) currentProject.exam.question_source_path = data.question_source_path;
  if (data.rubric_source_path) currentProject.exam.rubric_source_path = data.rubric_source_path;
  status.textContent = `✅ 저장 완료${rubric ? ' - 기존 기준표 사용' : ''}`;
  return true;
}

async function extractExamRubricFromFile(input) {
  if (!currentProject || !input.files.length) return false;
  const file = input.files[0];
  const status = document.getElementById('examSourceStatus');
  status.textContent = `⏳ "${file.name}"에서 공식 채점기준 추출 중...`;
  input.disabled = true;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/exam/rubric/extract`, {
      method: 'POST', body: fd,
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = `❌ ${data.error || '공식 채점기준표 추출 실패'}`;
      return false;
    }
    currentProject.exam.rubric_source_path = data.rubric_source_path;
    currentProject.exam.questions = data.questions;
    currentProject.total_max_score = data.total_max_score;
    currentProject.prompt_template = data.prompt_template;
    renderExamQuestions();
    status.textContent = `✅ 공식 기준표 ${data.questions.length}문항 적용 완료 - 아래에서 검토·편집하세요.`;
    return true;
  } catch (error) {
    status.textContent = `❌ 네트워크 오류: ${error.message}`;
    return false;
  } finally {
    input.disabled = false;
    input.value = '';
  }
}

async function generateExamRubric(preferSplitAnswers = false) {
  if (!currentProject) return;
  const status = document.getElementById(preferSplitAnswers ? 'examSplitStatus' : 'examSourceStatus');
  const question = document.getElementById('examQuestionFile').files[0];
  const rubric = document.getElementById('examRubricFile').files[0];
  if (!preferSplitAnswers && (question || rubric) && !await uploadExamSources()) return;
  status.style.color = 'var(--text2)';
  status.textContent = preferSplitAnswers
    ? '⏳ 학생별 답지를 비교하여 전체 문항과 채점기준을 만드는 중...'
    : '⏳ 문제 분석과 채점기준 생성 중...';
  const sourceMode = document.getElementById('examSourceMode')?.value || 'auto';
  const expectedQuestionCount = Math.max(0, parseInt(document.getElementById('examExpectedQuestionCount')?.value) || 0);
  currentProject.exam.source_mode = sourceMode;
  currentProject.exam.expected_question_count = expectedQuestionCount;
  const res = await fetch(`/api/projects/${currentProject.id}/exam/generate-rubric`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_mode: sourceMode,
      expected_question_count: expectedQuestionCount,
      prefer_split_answers: preferSplitAnswers,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    const found = data.questions?.length ? ` (현재 확인: ${data.questions.join(', ')}번)` : '';
    status.textContent = `❌ ${data.error}${found}`;
    status.style.color = 'var(--danger)';
    return;
  }
  currentProject.exam.questions = data.questions;
  currentProject.total_max_score = data.total_max_score;
  currentProject.prompt_template = data.prompt_template;
  renderExamQuestions();
  const sourceText = data.used_split_answers
    ? ` · 학생 답지 ${data.source_files_checked?.length || 1}개 비교`
    : (data.audit_performed ? ' · 누락 검증 완료' : '');
  if (data.warnings?.length) {
    status.textContent = `⚠️ ${data.questions.length}문항 추출${sourceText} · ${data.warnings.join(' / ')}`;
    status.style.color = 'var(--warning)';
  } else {
    status.textContent = `✅ ${data.questions.length}문항 ${data.used_rubric ? '기준표 추출' : '모범답안·기준 생성'} 완료${sourceText} - 서술형 시험 탭에서 검토하세요.`;
    status.style.color = 'var(--success)';
  }
}

async function generateExamRubricFromSplit() {
  return generateExamRubric(true);
}

function parseStudentLines() {
  return document.getElementById('examStudents').value.split(/\r?\n/).map((line, index) => {
    const match = line.trim().match(/^(\d+)\s*[,\t.\-]?\s*(.*)$/);
    if (!match) return null;
    return { number: parseInt(match[1]), name: match[2].trim() || `학생 ${match[1]}` };
  }).filter(Boolean);
}

async function saveExamStudents() {
  const students = parseStudentLines();
  if (!students.length) throw new Error('학생 명렬을 입력하세요.');
  const res = await fetch(`/api/projects/${currentProject.id}/exam/students`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ students }) });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || '학생 명렬 저장 실패');
  currentProject.exam.students = data.students;
}

async function uploadExamScan() {
  const file = document.getElementById('examScanFile').files[0];
  if (!file) return alert('통합 스캔 PDF를 선택하세요.');
  const fd = new FormData(); fd.append('scan_file', file);
  const status = document.getElementById('examScanStatus');
  status.textContent = '⏳ 통합 PDF 저장 중...';
  const res = await fetch(`/api/projects/${currentProject.id}/exam/sources`, { method: 'POST', body: fd });
  const data = await res.json();
  if (!res.ok) { status.textContent = `❌ ${data.error}`; return; }
  currentProject.exam.scan_split.source_path = data.scan_source_path;
  status.textContent = `✅ ${file.name} 저장 완료`;
}

function examSplitPayload() {
  return {
    start_page: parseInt(document.getElementById('examStartPage').value) || 1,
    pages_per_student: parseInt(document.getElementById('examPagesPerStudent').value) || 0,
    boundaries: document.getElementById('examBoundaries').value.split(',').map(v => parseInt(v.trim())).filter(Number.isFinite),
  };
}

function renderSplitPlan(data) {
  const el = document.getElementById('examSplitPreview');
  let html = `<div style="font-size:.85rem;margin-bottom:8px">전체 ${data.total_pages}쪽 · ${data.entries.length}명 · 방식: ${data.mode === 'fixed' ? '동일 쪽 수' : '개별 경계'}</div>`;
  html += '<div class="table-wrap"><table><thead><tr><th>번호</th><th>이름</th><th>페이지</th><th>쪽 수</th></tr></thead><tbody>';
  html += data.entries.map(e => `<tr><td>${e.number}</td><td>${esc(e.name)}</td><td>${e.start_page}~${e.end_page}</td><td>${e.page_count}</td></tr>`).join('');
  html += '</tbody></table></div>';
  if (data.unused_pages?.length) html += `<div style="color:var(--warning);margin-top:8px">사용하지 않는 뒤쪽 페이지: ${data.unused_pages.join(', ')}</div>`;
  el.innerHTML = html;
}

async function previewExamSplit() {
  const status = document.getElementById('examSplitStatus');
  try {
    await saveExamStudents();
    status.textContent = '⏳ 분할 계획 계산 중...';
    const res = await fetch(`/api/projects/${currentProject.id}/exam/split/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(examSplitPayload()) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    renderSplitPlan(data); status.textContent = '✅ 페이지 범위를 확인하세요.';
  } catch (e) { status.textContent = `❌ ${e.message}`; }
}

async function runExamSplit() {
  if (!confirm('미리보기의 페이지 범위대로 학생별 PDF를 생성하시겠습니까?')) return;
  const status = document.getElementById('examSplitStatus');
  try {
    await saveExamStudents(); status.textContent = '⏳ 학생별 PDF 생성·검증 중...';
    const res = await fetch(`/api/projects/${currentProject.id}/exam/split`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(examSplitPayload()) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    renderSplitPlan(data); status.textContent = `✅ ${data.entries.length}명 PDF 생성 완료 · 이제 '분할 답지에서 문항·기준 생성'을 누르세요.`;
    await selectProject(currentProject.id, true);
  } catch (e) { status.textContent = `❌ ${e.message}`; }
}

async function autoGeneratePrompt(statusEl, statusMsg) {
  // 카테고리 저장 후 프롬프트 자동 생성
  try {
    if (statusEl) {
      statusEl.textContent = statusMsg || '⏳ 프롬프트 자동 생성 중...';
      statusEl.style.color = 'var(--primary)';
    }
    await fetch(`/api/projects/${currentProject.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ categories: currentProject.categories }),
    });
    const res = await fetch(`/api/projects/${currentProject.id}/generate-prompt`, { method: 'POST' });
    const data = await res.json();
    document.getElementById('cfgPrompt').value = data.prompt;
    currentProject.prompt_template = data.prompt;
    return true;
  } catch(e) {
    console.error('프롬프트 자동 생성 실패:', e);
    return false;
  }
}

async function extractRubricFromFile(input) {
  if (!currentProject || !input.files.length) return;
  const file = input.files[0];
  const status = document.getElementById('rubricExtractStatus');
  status.textContent = `⏳ "${file.name}" 분석 중... (AI가 루브릭을 추출합니다)`;
  status.style.color = 'var(--primary)';
  
  const fd = new FormData();
  fd.append('file', file);
  
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/rubric/extract`, {
      method: 'POST', body: fd
    });
    const data = await res.json();
    input.value = '';
    
    if (!res.ok) {
      status.textContent = `❌ ${data.error || '추출 실패'}`;
      status.style.color = 'var(--danger)';
      return;
    }
    
    if (currentProject.categories?.length > 0) {
      if (!confirm('기존 채점 기준을 AI 추출 결과로 교체할까요?\n(취소하면 기존 기준 뒤에 추가됩니다)')) {
        currentProject.categories.push(...data.categories);
      } else {
        currentProject.categories = data.categories;
      }
    } else {
      currentProject.categories = data.categories;
    }
    
    // 프롬프트도 추출 결과에 있으면 반영, 아니면 자동 생성
    if (data.prompt_template) {
      currentProject.prompt_template = data.prompt_template;
      document.getElementById('cfgPrompt').value = data.prompt_template;
    }
    
    renderRubric();
    const totalCriteria = data.categories.reduce((s, c) => s + c.criteria.length, 0);
    status.textContent = `✅ ${data.categories.length}개 영역, ${totalCriteria}개 항목 추출 완료!`;
    status.style.color = 'var(--success)';
    
    // 프롬프트 자동 생성
    await autoGeneratePrompt(status, `✅ 루브릭 추출 완료! 프롬프트 생성 중...`);
    status.textContent = `✅ ${data.categories.length}개 영역, ${totalCriteria}개 항목 추출 및 프롬프트 생성 완료! (저장 버튼을 눌러 적용하세요)`;
    status.style.color = 'var(--success)';
  } catch (e) {
    status.textContent = `❌ 네트워크 오류: ${e.message}`;
    status.style.color = 'var(--danger)';
    input.value = '';
  }
}

async function generateRubricFromText() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  const textInput = document.getElementById('rubricTextInput');
  const text = textInput.value.trim();
  if (!text) return alert('루브릭 설명을 입력하세요.');
  
  const status = document.getElementById('rubricGenStatus');
  status.textContent = '⏳ AI가 루브릭을 생성하고 있습니다...';
  status.style.color = 'var(--primary)';
  
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/rubric/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    
    if (!res.ok) {
      status.textContent = `❌ ${data.error || '생성 실패'}`;
      status.style.color = 'var(--danger)';
      return;
    }
    
    if (!data.categories?.length) {
      status.textContent = '❌ AI가 루브릭을 생성하지 못했습니다. 설명을 더 구체적으로 작성해 주세요.';
      status.style.color = 'var(--danger)';
      return;
    }
    
    if (currentProject.categories?.length > 0) {
      if (!confirm('기존 채점 기준을 AI 생성 결과로 교체할까요?\n(취소하면 기존 기준 뒤에 추가됩니다)')) {
        currentProject.categories.push(...data.categories);
      } else {
        currentProject.categories = data.categories;
      }
    } else {
      currentProject.categories = data.categories;
    }
    
    renderRubric();
    const totalCriteria = data.categories.reduce((s, c) => s + c.criteria.length, 0);
    status.textContent = `✅ ${data.categories.length}개 영역, ${totalCriteria}개 항목 생성 완료! 프롬프트 생성 중...`;
    status.style.color = 'var(--success)';
    
    // 프롬프트 자동 생성
    await autoGeneratePrompt(status);
    status.textContent = `✅ ${data.categories.length}개 영역, ${totalCriteria}개 항목 생성 및 프롬프트 자동 생성 완료! (저장 버튼을 눌러 적용하세요)`;
    status.style.color = 'var(--success)';
  } catch (e) {
    status.textContent = `❌ 네트워크 오류: ${e.message}`;
    status.style.color = 'var(--danger)';
  }
}

async function generatePromptFromRubric() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  collectRubricFromEditor();
  if (!currentProject.categories?.length) return alert('루브릭이 없습니다. 먼저 영역을 추가하세요.');
  
  const ok = await autoGeneratePrompt(null);
  if (ok) {
    alert('✅ 현재 루브릭 기반으로 프롬프트가 생성되었습니다.\n아래 프롬프트를 확인하고 필요시 수정하세요.');
  } else {
    alert('❌ 프롬프트 생성에 실패했습니다.');
  }
}

// ═══ 심사자료 ═══

async function browseFolder() {
  const btn = document.getElementById('btnBrowseFolder');
  if (btn) { btn.innerHTML = '<span style="font-size:1.3em">⏳</span> 선택 중...'; btn.disabled = true; }
  try {
    const res = await fetch('/api/browse-folder', { method: 'POST' });
    const data = await res.json();
    if (data.path) {
      document.getElementById('matFolder').value = data.path;
      document.getElementById('matSource').value = 'folder';
      await saveMaterials();
    }
  } catch(e) {
    alert('폴더 선택 다이얼로그를 열 수 없습니다: ' + e.message);
  } finally {
    if (btn) { btn.innerHTML = '<span style="font-size:1.3em">📂</span> 폴더 선택'; btn.disabled = false; }
  }
}

async function addFiles() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  const btn = document.getElementById('btnAddFiles');
  const status = document.getElementById('addFilesStatus');
  if (btn) { btn.innerHTML = '<span style="font-size:1.1em">⏳</span> 선택 중...'; btn.disabled = true; }
  status.textContent = '';
  try {
    const fileTypes = document.getElementById('matTypes').value;
    const res = await fetch('/api/browse-files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: currentProject.id, file_types: fileTypes }),
    });
    const data = await res.json();
    if (!data.files || data.files.length === 0) return;

    // 중복 파일이 있는 경우
    if (data.duplicates && data.duplicates.length > 0) {
      const overwrite = confirm(
        `이미 존재하는 파일이 있습니다:\n${data.duplicates.join(', ')}\n\n덮어쓸까요?`
      );
      if (overwrite) {
        // 덮어쓰기로 재요청 (다이얼로그 없이)
        const res2 = await fetch('/api/browse-files', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: currentProject.id,
            file_types: fileTypes,
            overwrite: true,
            selected_files: data.files,
          }),
        });
        const data2 = await res2.json();
        status.textContent = `✅ ${data2.copied?.length || 0}개 파일 추가됨 (${data.duplicates.length}개 덮어쓰기)`;
        status.style.color = 'var(--success)';
      } else {
        status.textContent = `⚠️ 중복 파일이 있어 추가를 취소했습니다.`;
        status.style.color = 'var(--text2)';
        return;
      }
    } else {
      status.textContent = `✅ ${data.copied?.length || 0}개 파일 추가됨`;
      status.style.color = 'var(--success)';
    }
    // source_type 변경 없이 스캔만 새로고침
    await scanMaterials();
  } catch(e) {
    alert('파일 선택 다이얼로그를 열 수 없습니다: ' + e.message);
  } finally {
    if (btn) { btn.innerHTML = '<span style="font-size:1.1em">📄</span> 파일 추가'; btn.disabled = false; }
  }
}

function toggleMatSource() {
  // 통합 UI에서는 별도 토글 불필요
}

async function saveMaterials() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  const src = document.getElementById('matSource').value;
  const folder = document.getElementById('matFolder').value.trim();
  const types = document.getElementById('matTypes').value;
  const pattern = document.getElementById('matPattern').value;
  
  const body = {
    ...currentProject,
    materials: {
      source_type: src,
      folder_path: src === 'folder' ? folder : '',
      file_types: types.split(',').map(t => t.trim()).filter(Boolean),
      naming_pattern: pattern,
    }
  };
  
  const res = await fetch(`/api/projects/${currentProject.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  currentProject = await res.json();
  scanMaterials();
}

function populateMaterials() {
  if (!currentProject) return;
  const mat = currentProject.materials || {};
  document.getElementById('matSource').value = mat.source_type || 'folder';
  document.getElementById('matFolder').value = mat.folder_path || '';
  document.getElementById('matTypes').value = (mat.file_types || ['pdf']).join(',');
  document.getElementById('matPattern').value = mat.naming_pattern || '';
}

async function scanMaterials() {
  if (!currentProject) { document.getElementById('materialsList').innerHTML = '<div class="empty-state"><p>프로젝트를 먼저 선택하세요</p></div>'; return; }
  populateMaterials();
  const el = document.getElementById('materialsList');
  el.innerHTML = '<div class="empty-state"><div class="icon">⏳</div><p>자료를 스캔하는 중입니다. 잠시만 기다려주세요...</p></div>';
  const res = await fetch(`/api/projects/${currentProject.id}/materials`);
  const data = await res.json();
  // 스캔 데이터를 전역으로 저장 (결과 상세에서 참조)
  window._scannedMaterials = data.participants || [];
  if (!data.participants?.length) { el.innerHTML = '<div class="empty-state"><div class="icon">📂</div><p>심사자료가 없습니다. 위에서 폴더 또는 파일을 선택하세요.</p></div>'; return; }
  const totalFiles = data.participants.reduce((s, p) => s + p.files.length, 0);
  el.innerHTML = `<div style="margin-bottom:12px;display:flex;gap:16px;flex-wrap:wrap">
      <span class="badge badge-primary">👥 ${data.total_count}팀</span>
      <span class="badge badge-success">📄 ${totalFiles}개 파일</span>
      ${data.source_type === 'folder' && data.folder_path ? `<span class="badge" style="background:var(--surface2);color:var(--text2)">📁 ${esc(data.folder_path)}</span>` : ''}
    </div>
    <div class="table-wrap"><table><thead><tr><th style="width:30px"><input type="checkbox" id="checkAllMaterials" onclick="toggleAllMaterials(this.checked)"></th><th>번호</th><th>이름</th><th>파일 (${totalFiles}개)</th><th style="width:40px"></th></tr></thead><tbody>
    ${data.participants.map(p => `<tr>
      <td><input type="checkbox" class="participant-check" value="${p.number}"></td>
      <td>${p.number}</td>
      <td>${esc(p.name)}</td>
      <td>${p.files.map(f => `<span class="chip" style="cursor:pointer" onclick="openFile('${esc(f.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'"))}')" title="클릭하여 열기: ${esc(f.path)}">📄 ${esc(f.name)} (${f.size_mb}MB)</span>`).join(' ')}</td>
      <td>${p.files.map(f => `<button class="btn-icon" style="font-size:.7rem" onclick="removeMaterial('${esc(f.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'"))}','${esc(f.name)}')" title="${esc(f.name)} 제거">✕</button>`).join('')}</td>
    </tr>`).join('')}
    </tbody></table></div>`;
}

function toggleAllMaterials(checked) {
  document.querySelectorAll('.participant-check').forEach(el => el.checked = checked);
}

async function startSelectedGrading() {
  const selected = Array.from(document.querySelectorAll('.participant-check:checked')).map(el => parseInt(el.value));
  if (!selected.length) return alert('채점할 팀을 선택하세요.');
  if (confirm(`${selected.length}개 팀의 채점을 시작하시겠습니까?`)) {
    // 채점 탭으로 이동 (UI 편의성)
    const btn = document.querySelector('.sidebar button[onclick*="grading"]');
    if (btn) btn.click();
    startGrading(selected);
  }
}

async function openFile(filePath) {
  try {
    const res = await fetch('/api/open-file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath }),
    });
    const data = await res.json();
    if (!res.ok) alert(data.error || '파일 열기 실패');
  } catch(e) { alert('파일 열기 실패: ' + e.message); }
}

async function convertHwp() {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  const btn = document.getElementById('btnConvertHwp');
  const status = document.getElementById('hwpConvertStatus');
  btn.disabled = true;
  btn.innerHTML = '<span style="font-size:1.1em">⏳</span> 변환 중...';
  status.textContent = '문서(HWP/DOCX) → PDF 변환 중...';
  status.style.color = 'var(--primary)';
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/convert-hwp`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = `❌ ${data.error || '변환 실패'}`;
      status.style.color = 'var(--danger)';
      return;
    }
    if (data.converted > 0) {
      status.textContent = `✅ ${data.converted}개 파일 변환 완료!`;
      status.style.color = 'var(--success)';
      if (data.failed > 0) {
        status.textContent += ` (${data.failed}개 실패: ${data.failed_files.map(f => f.name).join(', ')})`;
      }
      await scanMaterials();
    } else {
      status.textContent = data.message || '변환할 문서 파일이 없습니다.';
      status.style.color = 'var(--text2)';
    }
  } catch(e) {
    status.textContent = `❌ 오류: ${e.message}`;
    status.style.color = 'var(--danger)';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span style="font-size:1.1em">🔄</span> 문서 → PDF 변환';
  }
}

async function removeMaterial(filePath, fileName) {
  if (!currentProject) return;
  if (!confirm(`"${fileName}" 파일을 심사 대상에서 제외할까요?\n(원본 파일은 삭제되지 않습니다)`)) return;
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/materials/remove`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath }),
    });
    await scanMaterials();
  } catch(e) { alert('제거 실패: ' + e.message); }
}

// ═══ 채점 실행 ═══
async function renderGradingGrid() {
  if (!currentProject) return;
  const el = document.getElementById('gradingTeamGrid');
  if (!el) return;
  el.innerHTML = '<div style="font-size: 0.85rem; color: var(--text2);">참가자 목록을 불러오는 중...</div>';
  try {
    const [matRes, statRes] = await Promise.all([
      fetch(`/api/projects/${currentProject.id}/materials`),
      fetch('/api/status')
    ]);
    const matData = await matRes.json();
    const statData = await statRes.json();
    
    if (!matData.participants?.length) {
      el.innerHTML = '<div style="font-size: 0.85rem; color: var(--text2);">심사자료가 없습니다.</div>';
      return;
    }
    
    let completedTeams = new Set();
    try {
      const resRes = await fetch(`/api/projects/${currentProject.id}/results`);
      if (resRes.ok) {
        const resData = await resRes.json();
        if (Array.isArray(resData)) resData.forEach(r => completedTeams.add(r.team_number));
      }
    } catch(e) {}
    
    el.innerHTML = matData.participants.map(t => `
      <div class="team-tile ${completedTeams.has(t.number) ? 'done' : ''}" id="tile-team-${t.number}">
        <div class="team-num">${t.number}번</div>
        <div class="team-name">${esc(t.name)}</div>
      </div>
    `).join('');
    updateStats();
  } catch (e) {
    el.innerHTML = '';
  }
}

async function startGrading(team_numbers = null) {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  // 사전 검증
  if (currentProject.project_type === 'exam') {
    if (!(currentProject.exam?.questions || []).length) return alert('서술형 문항과 채점 기준을 먼저 준비하세요.');
  } else {
    const cats = currentProject.categories || [];
    const totalCriteria = cats.reduce((s, c) => s + (c.criteria?.length || 0), 0);
    if (totalCriteria === 0) {
      return alert('채점 기준(Rubric)이 설정되지 않았습니다.\n\n설정 탭 → 채점 기준(Rubric)에서 영역과 항목을 추가하세요.');
    }
  }
  if (!currentProject.materials?.folder_path && currentProject.materials?.source_type === 'folder') {
    return alert('심사자료 폴더가 설정되지 않았습니다.\n\n심사자료 탭에서 폴더를 지정하세요.');
  }
  const body = {
    start_from: parseInt(document.getElementById('startFrom').value),
    delay: parseInt(document.getElementById('delay').value),
    repeat_count: parseInt(document.getElementById('repeatCount').value),
    new_round: document.getElementById('newRound').checked,
    team_numbers: team_numbers,
  };
  const res = await fetch(`/api/projects/${currentProject.id}/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error);
    return;
  }
  document.getElementById('btnStart').disabled = true;
  document.getElementById('btnStop').disabled = false;
  document.getElementById('gradingLog').innerHTML = '';
  renderGradingGrid();
  connectSSE();
}

async function stopGrading() {
  const res = await fetch('/api/stop', { method: 'POST' });
  const data = await res.json();
  document.getElementById('gradingCurrentStatus').textContent = data.pending
    ? '⏹ 중단 요청됨 - 현재 AI 응답 종료 후 멈춥니다. (웹에서는 몇 분 걸릴 수 있음)'
    : '중단할 채점이 없습니다.';
  document.getElementById('btnStop').disabled = true;
}

function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource('/api/events');
  eventSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    const log = document.getElementById('gradingLog');
    const time = new Date().toLocaleTimeString();
    let cls = 'info', msg = '';
    switch (data.type) {
      case 'team_start': 
        msg = `[${data.index}/${data.total}] ${data.name} (${data.team}번) 채점 시작`; 
        const ts = document.getElementById('tile-team-' + data.team);
        if (ts) { ts.className = 'team-tile current'; ts.scrollIntoView({behavior: 'smooth', block: 'nearest'}); }
        break;
      case 'step': msg = `  → ${data.step}`; break;
      case 'team_done': 
        msg = `✅ ${data.name} 완료 (${data.score}점)`; cls = 'success'; 
        const td = document.getElementById('tile-team-' + data.team);
        if (td) td.className = 'team-tile done';
        break;
      case 'team_error': 
        msg = `❌ ${data.name} 실패: ${data.error}`; cls = 'error'; 
        const te = document.getElementById('tile-team-' + data.team);
        if (te) te.className = 'team-tile error';
        break;
      case 'finished': msg = `🏁 채점 완료! 성공: ${data.success}, 실패: ${data.fail}`; cls = 'success';
        document.getElementById('btnStart').disabled = false; document.getElementById('btnStop').disabled = true;
        if (eventSource) { eventSource.close(); eventSource = null; }
        break;
      case 'stopped': msg = `⏹ ${data.message}`; cls = 'error';
        document.getElementById('btnStart').disabled = false; document.getElementById('btnStop').disabled = true;
        if (eventSource) { eventSource.close(); eventSource = null; }
        break;
    }
    if (msg) log.innerHTML += `<div class="log-entry ${cls}"><span class="time">${time}</span>${esc(msg)}</div>`;
    log.scrollTop = log.scrollHeight;
    updateStats();
  };
  eventSource.onerror = () => {
    // 자동 재연결 (EventSource 기본 동작), 상태만 폴링
    updateStats();
  };
}

async function updateStats() {
  let state = null;
  try {
    const res = await fetch('/api/status');
    state = await res.json();
    const status = document.getElementById('gradingCurrentStatus');
    if (status) {
      if (state.running) {
        const elapsed = state.team_started_at ? Math.max(0, Math.floor(Date.now() / 1000 - state.team_started_at)) : 0;
        const elapsedText = elapsed ? ` · ${Math.floor(elapsed / 60)}분 ${elapsed % 60}초` : '';
        status.textContent = `${state.current_team ? state.current_team + '번 · ' : ''}${state.current_step || '처리 중'}${elapsedText}`;
        document.getElementById('btnStart').disabled = true;
        if (!state.should_stop) document.getElementById('btnStop').disabled = false;
      } else if (!status.textContent.includes('완료') && !status.textContent.includes('중단')) {
        status.textContent = '';
      }
    }
  } catch(e) {}
  const tiles = document.querySelectorAll('#gradingTeamGrid .team-tile');
  if (tiles.length > 0) {
    const total = tiles.length;
    const done = document.querySelectorAll('#gradingTeamGrid .team-tile.done').length;
    const err = document.querySelectorAll('#gradingTeamGrid .team-tile.error').length;
    
    document.getElementById('statTotal').textContent = total;
    document.getElementById('statDone').textContent = done + err;
    document.getElementById('statSuccess').textContent = done;
    document.getElementById('statFail').textContent = err;
    
    const pct = total ? ((done + err) / total * 100) : 0;
    document.getElementById('gradingProgress').style.width = pct + '%';
  } else {
    try {
      const s = state || {};
      document.getElementById('statTotal').textContent = s.total_count;
      document.getElementById('statDone').textContent = s.completed_count;
      document.getElementById('statSuccess').textContent = s.success_count;
      document.getElementById('statFail').textContent = s.fail_count;
      const pct = s.total_count ? (s.completed_count / s.total_count * 100) : 0;
      document.getElementById('gradingProgress').style.width = pct + '%';
    } catch(e) {}
  }
}

// ═══ 결과 조회 ═══
async function loadRounds(selectId, cb) {
  if (!currentProject) return;
  const res = await fetch(`/api/projects/${currentProject.id}/rounds`);
  const rounds = await res.json();
  const sel = document.getElementById(selectId);
  sel.innerHTML = rounds.map(r => `<option value="${r.id}">${r.id}회차 (${r.count}팀)</option>`).join('');
  if (cb) cb();
}

let cachedResults = [];
let resultsSortCol = 'rank'; // 'rank' or 'number'
let resultsSortDir = 'asc';  // 'asc' or 'desc'

async function loadResults() {
  if (!currentProject) return;
  const round = document.getElementById('resultRound').value;
  const res = await fetch(`/api/projects/${currentProject.id}/results?round=${round}`);
  cachedResults = await res.json();
  resultsSortCol = 'rank'; resultsSortDir = 'asc';
  renderResultsTable();
}

function sortResults(col) {
  if (resultsSortCol === col) {
    resultsSortDir = resultsSortDir === 'asc' ? 'desc' : 'asc';
  } else {
    resultsSortCol = col;
    resultsSortDir = 'asc';
  }
  renderResultsTable();
}

function renderResultsTable() {
  const round = document.getElementById('resultRound').value;
  const tbody = document.getElementById('resultsBody');
  if (!cachedResults.length) { tbody.innerHTML = `<tr><td colspan="${currentProject?.project_type === 'exam' ? 6 : 5}" style="text-align:center;color:var(--text2)">결과 없음</td></tr>`; return; }
  
  // 원본 순위 매핑 (서버는 총점 내림차순)
  const rankMap = new Map();
  cachedResults.forEach((r, i) => rankMap.set(r.team_number, i + 1));
  
  const sorted = [...cachedResults];
  if (resultsSortCol === 'number') {
    sorted.sort((a, b) => resultsSortDir === 'asc' ? a.team_number - b.team_number : b.team_number - a.team_number);
  } else {
    // rank = 총점순
    if (resultsSortDir === 'desc') sorted.reverse();
  }
  
  // 헤더 화살표 업데이트 (항상 두 개 표시, 활성만 강조)
  const arrow = (col) => {
    if (resultsSortCol !== col) return '<span style="opacity:.3">▲</span><span style="opacity:.3">▼</span>';
    const upStyle = resultsSortDir === 'asc' ? 'opacity:1' : 'opacity:.3';
    const dnStyle = resultsSortDir === 'desc' ? 'opacity:1' : 'opacity:.3';
    return `<span style="${upStyle}">▲</span><span style="${dnStyle}">▼</span>`;
  };
  document.getElementById('thRank').innerHTML = `순위 ${arrow('rank')}`;
  document.getElementById('thNumber').innerHTML = `번호 ${arrow('number')}`;
  
  tbody.innerHTML = sorted.map((r) => {
    const rank = rankMap.get(r.team_number);
    const approval = r.teacher_status === 'approved'
      ? '<span class="badge badge-success">승인됨</span>'
      : `<span class="badge badge-warning">검토 대기${r.review_required_count ? ` ${r.review_required_count}건` : ''}</span>`;
    return `<tr class="clickable" onclick="showDetail(${r.team_number}, ${round})">
      <td>${rank}</td><td>${r.team_number}</td><td>${esc(r.team_name || '')}</td>
      <td><strong>${r.total_score ?? '-'}</strong></td>
      ${currentProject?.project_type === 'exam' ? `<td>${approval}</td>` : ''}
      <td style="display:flex;gap:4px">
        <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();showDetail(${r.team_number}, ${round})">상세</button>
        <button class="btn btn-warning btn-sm" onclick="event.stopPropagation();regradeSingle(${r.team_number})">🔄 재채점</button>
      </td>
    </tr>`;
  }).join('');
}

async function regradeSingle(teamNum) {
  if (!confirm(`${teamNum}번 학생을 현재 회차에서 다시 채점하시겠습니까?\n(기존 결과가 덮어씌워집니다)`)) return;
  const btn = document.querySelector('.sidebar button[onclick*="grading"]');
  if (btn) btn.click();
  const newRoundCheck = document.getElementById('newRound');
  if (newRoundCheck) newRoundCheck.checked = false;
  startGrading([teamNum]);
}

let currentDetailData = null;
let currentDetailRound = null;

async function showDetail(teamNum, round) {
  if (!currentProject) return;
  const res = await fetch(`/api/projects/${currentProject.id}/result/${teamNum}?round=${round}`);
  const data = await res.json();
  currentDetailData = data;
  currentDetailRound = round;
  renderDetail(false);
  openModal('detailModal');
}

function renderDetail(isEdit = false) {
  const data = currentDetailData;
  const teamNum = data.team_number;
  const round = currentDetailRound;
  
  let titleHtml = `[${teamNum}번] ${esc(data.team_name || '')}`;
  const isExam = currentProject?.project_type === 'exam';
  const approveButton = isExam && data.teacher_status !== 'approved'
    ? `<button class="btn btn-success btn-sm" onclick="approveExamResult(${teamNum}, ${round})">✅ 최종 승인</button>` : '';
  const headerAction = isEdit 
    ? `<button class="btn btn-success btn-sm" onclick="saveManualEdit(${teamNum}, ${round})">💾 저장</button>
       <button class="btn btn-secondary btn-sm" onclick="renderDetail(false)">취소</button>`
    : `<button class="btn btn-primary btn-sm" onclick="renderDetail(true)">✏️ 수정</button>${approveButton}`;
  
  document.getElementById('detailTitle').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;width:100%;padding-right:30px">
    <span>${titleHtml}</span>
    <div style="display:flex;gap:8px">${headerAction}</div>
  </div>`;

  let html = isExam
    ? '<table><thead><tr><th>문항</th><th>답안 요약</th><th>점수</th><th>채점 근거</th><th>검토</th></tr></thead><tbody>'
    : '<table><thead><tr><th>영역</th><th>항목</th><th>점수</th><th>채점 근거</th></tr></thead><tbody>';

  if (isExam) {
    for (const q of (currentProject.exam?.questions || [])) {
      const score = data[q.id] ?? '';
      const reason = data[q.id + '_reason'] || '';
      const summary = data[q.id + '_answer_summary'] || '';
      const review = !!data[q.id + '_review_required'];
      const confidence = data[q.id + '_confidence'];
      const scoreCell = isEdit
        ? `<input type="number" class="edit-score" data-id="${q.id}" value="${score}" style="width:60px" min="0" max="${q.max_score}">`
        : `<strong>${score === '' ? '-' : score}/${q.max_score}</strong>`;
      const reasonCell = isEdit
        ? `<textarea class="edit-reason" data-id="${q.id}" rows="2" style="width:100%">${esc(reason)}</textarea>`
        : esc(reason || '-');
      const reviewCell = isEdit
        ? `<input type="checkbox" class="edit-review" data-id="${q.id}" ${review ? 'checked' : ''}>`
        : (review ? '<span class="badge badge-warning">확인 필요</span>' : '<span class="badge badge-success">정상</span>');
      html += `<tr><td>${esc(q.number)}번</td><td>${esc(summary || '-')}<br><small>확신도: ${confidence ?? '-'}</small></td><td>${scoreCell}</td><td>${reasonCell}</td><td>${reviewCell}</td></tr>`;
    }
  } else {
    for (const cat of (currentProject.categories || [])) {
      for (const c of cat.criteria) {
        const score = data[c.id] ?? '';
        const reason = data[c.id + '_reason'] || '';
        const scoreCell = isEdit
          ? `<input type="number" class="edit-score" data-id="${c.id}" value="${score}" style="width:60px" min="0" max="${c.max_score || 100}">`
          : `<strong>${score || '-'}</strong>`;
        const reasonCell = isEdit
          ? `<textarea class="edit-reason" data-id="${c.id}" rows="1" style="width:100%;font-family:inherit;font-size:.85rem;padding:4px">${esc(reason)}</textarea>`
          : esc(reason || '-');
        html += `<tr><td>${esc(cat.name)}</td><td>${esc(c.name)}</td><td>${scoreCell}</td><td>${reasonCell}</td></tr>`;
      }
    }
  }
  html += `</tbody></table>`;
  
  const commentCell = isEdit
    ? `<textarea id="editComment" style="width:100%;min-height:100px;line-height:1.6;font-family:inherit;padding:8px">${esc(data.overall_comment || '')}</textarea>`
    : `<p style="line-height:1.8">${esc(data.overall_comment || '-')}</p>`;
    
  html += `<div class="card" style="margin-top:16px"><h3>종합 의견</h3>${commentCell}</div>`;
  
  if (data.seteuk || isEdit) {
    const seteukCell = isEdit
      ? `<textarea id="editSeteuk" style="width:100%;min-height:120px;font-size:.9rem;line-height:1.6;font-family:inherit;padding:8px">${esc(data.seteuk || '')}</textarea>`
      : `<p id="seteukText" style="line-height:1.8;font-size:.9rem">${esc(data.seteuk || '')}</p>`;

    html += `<div class="card" style="margin-top:12px;background:var(--surface2)">
      <div style="display:flex;justify-content:space-between;align-items:center"><h3>📝 세특 문구</h3>
      ${isEdit ? '' : `<button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('seteukText').innerText);this.textContent='✅ 복사됨';setTimeout(()=>this.textContent='📋 복사',1500)">📋 복사</button>`}
      </div>
      ${seteukCell}
      ${isEdit ? '' : `<div style="text-align:right;font-size:.75rem;color:var(--text2)">${(data.seteuk || '').length}자</div>`}
    </div>`;
  }
  
  html += `<div style="text-align:right;margin-top:12px;font-size:1.1rem"><strong>총점: ${data.total_score ?? '-'}</strong></div>`;
  if (isExam) {
    const statusLabel = data.teacher_status === 'approved' ? `✅ 교사 승인 완료 (${esc(data.teacher_approved_at || '')})` : '⚠️ 교사 승인 전 임시 점수';
    html += `<div class="card" style="margin-top:12px;background:var(--surface2)"><strong>${statusLabel}</strong>${data.teacher_note ? `<p>${esc(data.teacher_note)}</p>` : ''}</div>`;
  }
  
  const participant = (window._scannedMaterials || []).find(p => p.number === teamNum);
  if (participant && participant.files?.length) {
    html += `<div class="card" style="margin-top:12px;background:var(--surface2)">
      <h3>📂 심사자료 원본</h3>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${participant.files.map(f => `<span class="chip" style="cursor:pointer" onclick="openFile('${esc(f.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'"))}')" title="클릭하여 열기">📄 ${esc(f.name)}</span>`).join('')}
      </div>
    </div>`;
  }
  
  document.getElementById('detailContent').innerHTML = html;
}

async function saveManualEdit(teamNum, round) {
  const payload = {
    overall_comment: document.getElementById('editComment')?.value || '',
    seteuk: document.getElementById('editSeteuk') ? document.getElementById('editSeteuk').value : ''
  };
  
  document.querySelectorAll('.edit-score').forEach(el => {
    payload[el.dataset.id] = parseFloat(el.value) || 0;
  });
  document.querySelectorAll('.edit-reason').forEach(el => {
    payload[el.dataset.id + '_reason'] = el.value;
  });
  document.querySelectorAll('.edit-review').forEach(el => {
    payload[el.dataset.id + '_review_required'] = el.checked;
  });
  
  const res = await fetch(`/api/projects/${currentProject.id}/result/${teamNum}?round=${round}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  
  const result = await res.json();
  if (res.ok) {
    currentDetailData = result.data;
    renderDetail(false);
    loadResults(); 
  } else {
    alert('저장 실패: ' + result.error);
  }
}

async function approveExamResult(teamNum, round) {
  const note = prompt('승인 메모가 있으면 입력하세요. (선택)', currentDetailData.teacher_note || '');
  if (note === null) return;
  if (!confirm('현재 점수를 최종 확정하시겠습니까?')) return;
  const res = await fetch(`/api/projects/${currentProject.id}/result/${teamNum}/approve?round=${round}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ teacher_note: note })
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '승인 실패');
  currentDetailData = data.data;
  renderDetail(false);
  loadResults();
}

async function downloadResults() {
  if (!currentProject) return;
  const round = document.getElementById('resultRound').value;
  window.location.href = `/api/projects/${currentProject.id}/download?round=${round}`;
}

// ═══ 종합 분석 ═══

async function loadRoundsForAnalysis() {
  if (!currentProject) return;
  const res = await fetch(`/api/projects/${currentProject.id}/rounds`);
  const rounds = await res.json();
  const el = document.getElementById('analysisRoundChecks');
  el.innerHTML = rounds.map(r =>
    `<label style="display:flex;align-items:center;gap:4px;font-size:.85rem;background:var(--surface2);padding:4px 10px;border-radius:6px;cursor:pointer">
      <input type="checkbox" class="analysis-round-cb" value="${r.id}" checked> ${r.id}회차 (${r.count}팀)
    </label>`
  ).join('');
  // 수동 채점 상태 확인
  checkManualScores();
}

async function checkManualScores() {
  if (!currentProject) return;
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/manual-scores`);
    const data = await res.json();
    const st = document.getElementById('manualStatus');
    if (data.count > 0) {
      st.textContent = `✅ ${data.count}팀 수동채점 로드됨`;
      st.style.color = 'var(--success)';
    } else {
      st.textContent = '';
    }
  } catch(e) {}
}

async function uploadManualScores(input) {
  if (!currentProject || !input.files.length) return;
  const fd = new FormData();
  fd.append('file', input.files[0]);
  const st = document.getElementById('manualStatus');
  st.textContent = '⏳ 업로드 중...';
  st.style.color = 'var(--primary)';
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/manual-scores/upload`, {
      method: 'POST', body: fd
    });
    const data = await res.json();
    input.value = '';
    if (res.ok) {
      st.textContent = `✅ ${data.count}팀 수동채점 로드됨`;
      st.style.color = 'var(--success)';
    } else {
      st.textContent = `❌ ${data.error}`;
      st.style.color = 'var(--danger)';
    }
  } catch(e) {
    st.textContent = `❌ ${e.message}`;
    st.style.color = 'var(--danger)';
    input.value = '';
  }
}

async function runAnalysis() {
  if (!currentProject) return;
  const checks = document.querySelectorAll('.analysis-round-cb:checked');
  const rounds = Array.from(checks).map(c => c.value).join(',');
  const includeManual = document.getElementById('includeManual').checked;
  
  if (!rounds && !includeManual) return alert('분석할 회차를 선택하거나 수동 채점을 포함하세요.');
  
  const res = await fetch(`/api/projects/${currentProject.id}/analysis?rounds=${rounds}&include_manual=${includeManual}`);
  const results = await res.json();
  
  if (!results.length) {
    document.getElementById('analysisBody').innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text2)">데이터 없음</td></tr>';
    return;
  }
  
  // 동적 헤더 생성
  const roundIds = [...new Set(results.flatMap(r => Object.keys(r.scores_by_round || {})))];
  let headHtml = '<th>순위</th><th>번호</th><th>이름</th>';
  roundIds.forEach(rid => headHtml += `<th>${esc(rid)}</th>`);
  headHtml += '<th>수동</th><th>평균</th><th>절사평균</th><th>편차</th><th>차이(AI-수동)</th>';
  document.getElementById('analysisHead').innerHTML = headHtml;
  
  // 데이터 행
  const tbody = document.getElementById('analysisBody');
  tbody.innerHTML = results.map((r, i) => {
    let html = `<tr><td>${i + 1}</td><td>${r.team_number}</td><td>${esc(r.team_name || '')}</td>`;
    roundIds.forEach(rid => html += `<td>${r.scores_by_round?.[rid] ?? '-'}</td>`);
    const manual = r.manual_score != null ? r.manual_score : '-';
    const diff = r.manual_score != null ? (r.average - r.manual_score).toFixed(1) : '-';
    html += `<td>${manual}</td><td><strong>${r.average}</strong></td>`;
    html += `<td>${r.is_trimmed ? r.trimmed_average : '-'}</td>`;
    html += `<td>${r.std_dev}</td><td>${diff}</td></tr>`;
    return html;
  }).join('');
}

async function downloadAnalysisExcel() {
  if (!currentProject) return;
  const checks = document.querySelectorAll('.analysis-round-cb:checked');
  const rounds = Array.from(checks).map(c => c.value).join(',');
  const includeManual = document.getElementById('includeManual').checked;
  window.location.href = `/api/projects/${currentProject.id}/analysis/excel?rounds=${rounds}&include_manual=${includeManual}`;
}

// ═══ 제출용 ═══
let previewResults = null;  // 미리보기 결과 저장

async function loadSubmission() {
  if (!currentProject) return;
  const round = document.getElementById('subRound').value;
  const res = await fetch(`/api/projects/${currentProject.id}/results?round=${round}`);
  submissionData = await res.json();
  previewResults = null;
  document.getElementById('btnExportExcel').disabled = true;
  document.getElementById('submissionPreview').innerHTML = '';
  renderSubmission();
}

async function loadAllTeamsSubmission() {
  if (!currentProject) return;
  const res = await fetch(`/api/projects/${currentProject.id}/materials`);
  const data = await res.json();
  if (!data.participants?.length) return alert('심사자료가 없습니다. 심사자료 탭에서 폴더를 지정하세요.');
  
  submissionData = data.participants.map(p => ({
    team_number: p.number,
    team_name: p.name,
    total_score: null
  }));
  previewResults = null;
  document.getElementById('btnExportExcel').disabled = true;
  document.getElementById('submissionPreview').innerHTML = '';
  renderSubmission();
}

function renderSubmission() {
  const tbody = document.getElementById('submissionBody');
  tbody.innerHTML = submissionData.map((r, i) => {
    const val = r.total_score != null ? r.total_score : '';
    return `
    <tr draggable="true" ondragstart="dragStart(event,${i})" ondragover="dragOver(event)" ondrop="drop(event,${i})">
      <td class="drag-handle">☰</td><td>${i + 1}</td><td>${r.team_number}</td><td>${esc(r.team_name || '')}</td>
      <td>${r.total_score ?? '-'}</td>
      <td><input type="number" value="${val}" min="0"
        style="width:80px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:4px 8px;color:var(--text)"
        onchange="validateAndSetScore(${i}, this)"></td>
    </tr>`;
  }).join('');
}

function validateAndSetScore(index, inputEl) {
  const val = inputEl.value.trim();
  if (val === '') {
    submissionData[index].total_score = null;
    renderSubmission();
    return;
  }
  const score = Number(val);
  if (isNaN(score)) { inputEl.value = ''; return; }
  
  // 위쪽(고순위) 팀 중 고정 점수가 있으면, 그보다 높으면 안 됨
  for (let i = index - 1; i >= 0; i--) {
    if (submissionData[i].total_score != null) {
      if (score > submissionData[i].total_score) {
        alert(`${index + 1}위의 점수(${score})가 ${i + 1}위(${submissionData[i].total_score}점)보다 높을 수 없습니다.`);
        inputEl.value = submissionData[index].total_score ?? '';
        return;
      }
      break;
    }
  }
  // 아래쪽(저순위) 팀 중 고정 점수가 있으면, 그보다 낮으면 안 됨
  for (let i = index + 1; i < submissionData.length; i++) {
    if (submissionData[i].total_score != null) {
      if (score < submissionData[i].total_score) {
        alert(`${index + 1}위의 점수(${score})가 ${i + 1}위(${submissionData[i].total_score}점)보다 낮을 수 없습니다.`);
        inputEl.value = submissionData[index].total_score ?? '';
        return;
      }
      break;
    }
  }
  
  submissionData[index].total_score = score;
  renderSubmission();
}

let dragIdx = null;
function dragStart(e, i) { dragIdx = i; e.dataTransfer.effectAllowed = 'move'; }
function dragOver(e) { e.preventDefault(); }
function drop(e, i) {
  e.preventDefault();
  if (dragIdx === null) return;
  const item = submissionData.splice(dragIdx, 1)[0];
  submissionData.splice(i, 0, item);
  dragIdx = null;
  // 드래그 후 고정 점수가 순위에 어긋나면 초기화
  for (let k = 1; k < submissionData.length; k++) {
    const prev = submissionData[k - 1].total_score;
    const curr = submissionData[k].total_score;
    if (prev != null && curr != null && curr > prev) {
      submissionData[k].total_score = null;
    }
  }
  previewResults = null;
  document.getElementById('btnExportExcel').disabled = true;
  document.getElementById('submissionPreview').innerHTML = '';
  renderSubmission();
}

async function previewSubmission() {
  if (!currentProject || !submissionData.length) return alert('먼저 팀을 불러오세요.');
  
  // 입력 필드 값 최신화
  const inputs = document.querySelectorAll('#submissionBody input[type="number"]');
  inputs.forEach((inp, i) => {
    submissionData[i].total_score = inp.value === '' ? null : Number(inp.value);
  });
  
  const teams = submissionData.map((r, i) => ({
    team_number: r.team_number,
    team_name: r.team_name,
    total_score: r.total_score
  }));
  
  const preview = document.getElementById('submissionPreview');
  preview.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text2)">⏳ 채점표 생성 중...</div>';
  
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/submission/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ teams })
    });
    if (!res.ok) {
      const err = await res.json();
      preview.innerHTML = `<div style="color:var(--danger)">${err.error || '오류 발생'}</div>`;
      return;
    }
    const data = await res.json();
    previewResults = data.results;
    const cats = data.categories;
    
    // 미리보기 테이블 렌더링
    let html = '<h3 style="margin-bottom:12px">📋 생성된 채점표 미리보기</h3>';
    html += '<div class="table-wrap"><table><thead><tr>';
    html += '<th>순위</th><th>번호</th><th>이름</th>';
    for (const cat of cats) {
      for (const c of cat.criteria) {
        html += `<th>${esc(c.name)}<br><small>(${c.max_score})</small></th>`;
      }
      html += `<th style="font-weight:700">${esc(cat.name)}<br>소계</th>`;
    }
    html += '<th style="font-weight:700">합계</th></tr></thead><tbody>';
    
    for (const r of previewResults) {
      html += `<tr><td>${r.rank}</td><td>${r.team_number}</td><td>${esc(r.team_name || '')}</td>`;
      for (const cat of cats) {
        for (const c of cat.criteria) {
          html += `<td>${r[c.id] ?? '-'}</td>`;
        }
        const catKey = cat.name.replace(/ /g, '_') + '_total';
        html += `<td style="font-weight:700">${r[catKey] ?? '-'}</td>`;
      }
      html += `<td style="font-weight:700">${r.total_score ?? '-'}</td></tr>`;
    }
    html += '</tbody></table></div>';
    preview.innerHTML = html;
    
    document.getElementById('btnExportExcel').disabled = false;
  } catch (e) {
    preview.innerHTML = `<div style="color:var(--danger)">네트워크 오류: ${e.message}</div>`;
  }
}

async function exportSubmissionExcel() {
  if (!currentProject || !previewResults) return;
  
  const res = await fetch(`/api/projects/${currentProject.id}/submission/excel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ results: previewResults })
  });
  if (res.ok) {
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = '제출용_채점표.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  } else {
    alert('Excel 생성 실패');
  }
}

// ═══ API 키 ═══
async function openKeyModal() {
  const res = await fetch('/api/keys');
  const data = await res.json();
  document.getElementById('keyFields').innerHTML = `
    <div class="form-group">
      <label>Google (Gemini) ${data.has_keys?.['google'] ? '<span class="badge badge-success">설정됨</span>' : '<span class="badge badge-danger">미설정</span>'}</label>
      <input id="key_google" value="${data.keys?.['google'] || ''}" placeholder="Google AI API 키 입력" type="password">
    </div>
    <div class="form-group">
      <label>OpenAI (GPT) ${data.has_keys?.['openai'] ? '<span class="badge badge-success">설정됨</span>' : '<span class="badge badge-danger">미설정</span>'}</label>
      <input id="key_openai" value="${data.keys?.['openai'] || ''}" placeholder="platform.openai.com API 키 입력" type="password">
    </div>`;
  openModal('keyModal');
}

async function saveKeys() {
  const payload = {};
  const googleKey = document.getElementById('key_google').value;
  const openaiKey = document.getElementById('key_openai')?.value;
  if (googleKey) payload.google = googleKey;
  if (openaiKey) payload.openai = openaiKey;
  if (Object.keys(payload).length) {
    await fetch('/api/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  }
  closeModal('keyModal');
  alert('API 키가 저장되었습니다');
}

// ═══ 유틸 ═══
function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// ═══ 초기화 ═══
document.addEventListener('DOMContentLoaded', async () => {
  await loadProviders();
  await loadModels();
  await loadProjects();
  const lastId = localStorage.getItem('lastProjectId');
  if (lastId && !currentProject) {
    try {
      await selectProject(lastId, true);
      showTab('settings');
    } catch(e) {}
  }
  setInterval(updateStats, 3000);
});

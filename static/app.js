// ═══ 전역 상태 ═══
let currentProject = null;
let eventSource = null;
let submissionData = [];
let currentOverview = null;
let wizardStep = 1;
let currentSubmissionStatus = null;
let submissionFilesByIndex = [];
let currentCriteriaVersions = null;
let pendingCriteriaSource = null;
let currentGradingRounds = [];
let currentRegradeCandidates = [];
let gradingPlanTimer = null;
let currentReviewDashboard = null;
let currentReviewStudent = null;

const WORKFLOW_LABELS = {
  report: '보고서·수행평가',
  competition: '대회·탐구 심사',
  exam: '정기고사 서술형',
};
const TAB_TO_STAGE = {
  overview: 'overview',
  settings: 'criteria',
  exam: 'criteria',
  materials: 'submissions',
  grading: 'grading',
  results: 'review',
  analysis: 'analysis',
};

// ═══ 탭 전환 ═══
function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('[data-stage]').forEach(t => t.classList.remove('active'));
  const el = document.getElementById('tab-' + name);
  if (el) el.classList.add('active');
  const stage = TAB_TO_STAGE[name];
  if (stage) document.querySelectorAll(`[data-stage="${stage}"]`).forEach(t => t.classList.add('active'));
  const tabs = document.getElementById('mainTabs');
  if (tabs) tabs.style.display = currentProject && name !== 'projects' ? '' : 'none';
  if (name === 'overview') loadOverview();
  if (name === 'results') {
    loadReviewDashboard();
    loadRounds('resultRound', () => loadResults());
    loadRoundsForAnalysis();
  }
  if (name === 'analysis') {
    loadRoundsForAnalysis();
    loadFeedbackExportPreview();
    if (currentProject?.workflow_type === 'competition') {
      loadCompetitionState();
      loadRounds('subRound', () => loadSubmission());
    }
  }
  if (name === 'materials') scanMaterials();
  if (name === 'grading') {
    renderGradingGrid();
    updateGradingRoundContext();
    loadGradingRounds();
    updateGradingPlanEstimate();
  }
}

function showWorkspaceStage(stage) {
  if (!currentProject) {
    showTab('projects');
    return;
  }
  const tab = stage === 'criteria'
    ? (currentProject.project_type === 'exam' ? 'exam' : 'settings')
    : ({
        overview: 'overview',
        submissions: 'materials',
        grading: 'grading',
        review: 'results',
        analysis: 'analysis',
      }[stage] || 'overview');
  showTab(tab);
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
      <span class="workflow-badge">${esc(WORKFLOW_LABELS[p.workflow_type] || (p.project_type === 'exam' ? WORKFLOW_LABELS.exam : WORKFLOW_LABELS.report))}</span>
      <h3>${esc(p.name)}</h3>
      <div class="meta">
        <span>📏 ${p.criteria_count}개 항목</span>
        <span>📊 ${p.round_count}회차</span>
        <span>👥 ${p.team_count}${p.project_type === 'exam' ? '명' : '팀'}</span>
      </div>
      <div class="meta" style="margin-top:4px"><span>🤖 ${esc(p.ai_provider || 'gemini_api')}</span><span>${p.updated_at ? `최근 수정 ${formatDateTime(p.updated_at)}` : ''}</span></div>
      <div style="margin-top:8px;text-align:right">
        <button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteProject('${p.id}')">삭제</button>
      </div>
    </div>
  `).join('');
}

async function selectProject(id, skipTabSwitch) {
  const res = await fetch(`/api/projects/${id}`);
  if (!res.ok) throw new Error('프로젝트를 불러오지 못했습니다.');
  currentProject = await res.json();
  currentSubmissionStatus = null;
  submissionFilesByIndex = [];
  currentStandardizationWorkspace = null;
  currentStandardizationSession = null;
  currentStandardizationSummary = null;
  currentProject.workflow_type = currentProject.workflow_type || (currentProject.project_type === 'exam' ? 'exam' : 'report');
  updateAppShell();
  localStorage.setItem('lastProjectId', id);
  await populateSettings();
  if (!skipTabSwitch) showWorkspaceStage('overview');
  loadProjects();
}

function updateAppShell() {
  const header = document.getElementById('headerProject');
  const meta = document.getElementById('headerMeta');
  const settingsButton = document.getElementById('projectSettingsButton');
  const tabs = document.getElementById('mainTabs');
  if (!currentProject) {
    header.textContent = '프로젝트를 선택하세요';
    meta.style.display = 'none';
    settingsButton.style.display = 'none';
    tabs.style.display = 'none';
    return;
  }
  const label = WORKFLOW_LABELS[currentProject.workflow_type] || WORKFLOW_LABELS.report;
  header.textContent = currentProject.name;
  meta.innerHTML = `<span>${esc(label)}</span><span class="dot"></span><span>${currentProject.total_max_score || 100}점</span>`;
  meta.style.display = '';
  settingsButton.style.display = '';
  tabs.style.display = '';
}

function openNewProjectModal() {
  wizardStep = 1;
  document.getElementById('newProjName').value = '';
  document.getElementById('newProjTarget').value = '';
  document.getElementById('newProjAssessment').value = '';
  document.getElementById('newProjTotalScore').value = '100';
  document.getElementById('newProjParticipantMode').value = 'individual';
  document.getElementById('newProjExpectedCount').value = '0';
  document.getElementById('newProjDesc').value = '';
  document.querySelector('input[name="newAISetupMode"][value="recommended"]').checked = true;
  selectWorkflowType('report');
  updateWizardAISettings();
  renderWizardStep();
  openModal('newProjectModal');
}

function selectWorkflowType(type) {
  if (!WORKFLOW_LABELS[type]) return;
  document.getElementById('newProjType').value = type;
  document.querySelectorAll('[data-workflow-type]').forEach(button => {
    button.classList.toggle('selected', button.dataset.workflowType === type);
  });
  renderWizardMaterialOptions();
}

function renderWizardMaterialOptions() {
  const type = document.getElementById('newProjType')?.value || 'report';
  const options = type === 'exam'
    ? [
        ['official_rubric', '공식 채점기준표 있음', '문제·정답·채점기준표를 등록하여 엄격하게 적용'],
        ['questions_answers', '문제와 정답 있음', '모범답안과 부분점 기준 초안을 AI가 생성'],
        ['questions_only', '문제만 있음', '모범답안과 채점기준을 함께 생성'],
        ['answers_focused', '정답 자료 중심', '답안지에 실제 작성된 문항을 중심으로 준비'],
        ['pregrade_first', '먼저 답안을 보고 기준화', '자율 선채점 후 실제 답안 유형으로 기준 보정'],
      ]
    : [
        ['rubric_ready', '루브릭 있음', '기존 평가표나 루브릭을 등록하여 사용'],
        ['generate_rubric', '간단한 설명으로 생성', '평가 목적을 입력해 루브릭 초안을 생성'],
        ['later', '나중에 준비', '프로젝트를 만든 뒤 평가기준 단계에서 선택'],
      ];
  const el = document.getElementById('newProjMaterialOptions');
  if (!el) return;
  el.innerHTML = options.map((option, index) => `
    <label class="option-card">
      <input type="radio" name="newMaterialStatus" value="${option[0]}" ${index === 0 ? 'checked' : ''}>
      <span><strong>${option[1]}</strong><small>${option[2]}</small></span>
    </label>
  `).join('');
}

function renderWizardStep() {
  document.querySelectorAll('[data-wizard-step]').forEach(panel => {
    panel.classList.toggle('active', Number(panel.dataset.wizardStep) === wizardStep);
  });
  document.querySelectorAll('[data-wizard-indicator]').forEach(indicator => {
    indicator.classList.toggle('active', Number(indicator.dataset.wizardIndicator) === wizardStep);
  });
  document.getElementById('wizardBackButton').style.visibility = wizardStep === 1 ? 'hidden' : 'visible';
  document.getElementById('wizardNextButton').style.display = wizardStep === 4 ? 'none' : '';
  document.getElementById('wizardCreateButton').style.display = wizardStep === 4 ? '' : 'none';
  document.getElementById('wizardValidation').textContent = '';
}

function changeWizardStep(delta) {
  if (delta > 0 && wizardStep === 2 && !document.getElementById('newProjName').value.trim()) {
    document.getElementById('wizardValidation').textContent = '프로젝트 이름을 입력하세요.';
    document.getElementById('newProjName').focus();
    return;
  }
  wizardStep = Math.max(1, Math.min(4, wizardStep + delta));
  renderWizardStep();
}

function updateWizardAISettings() {
  const mode = document.querySelector('input[name="newAISetupMode"]:checked')?.value || 'recommended';
  document.getElementById('wizardAdvancedAI').style.display = mode === 'advanced' ? '' : 'none';
}

async function populateWizardProviders() {
  const res = await fetch('/api/providers');
  const providers = await res.json();
  const select = document.getElementById('newProjProvider');
  select.innerHTML = providers.filter(p => !p.disabled).map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  await updateWizardModels();
}

async function updateWizardModels() {
  const provider = document.getElementById('newProjProvider')?.value || 'openai_api';
  const res = await fetch(`/api/models?provider=${encodeURIComponent(provider)}`);
  const models = await res.json();
  document.getElementById('newProjModel').innerHTML = Object.entries(models)
    .map(([id, model]) => `<option value="${id}">${esc(model.name)}</option>`).join('');
}

async function createProject() {
  const name = document.getElementById('newProjName').value.trim();
  if (!name) {
    wizardStep = 2;
    renderWizardStep();
    document.getElementById('wizardValidation').textContent = '프로젝트 이름을 입력하세요.';
    return;
  }
  const workflowType = document.getElementById('newProjType').value;
  const aiSetupMode = document.querySelector('input[name="newAISetupMode"]:checked')?.value || 'recommended';
  const body = {
    name,
    description: document.getElementById('newProjDesc').value.trim(),
    workflow_type: workflowType,
    project_type: workflowType === 'exam' ? 'exam' : 'report',
    total_max_score: Math.max(1, parseInt(document.getElementById('newProjTotalScore').value) || 100),
    setup: {
      target: document.getElementById('newProjTarget').value.trim(),
      assessment_name: document.getElementById('newProjAssessment').value.trim(),
      participant_mode: document.getElementById('newProjParticipantMode').value,
      expected_count: Math.max(0, parseInt(document.getElementById('newProjExpectedCount').value) || 0),
      materials_status: document.querySelector('input[name="newMaterialStatus"]:checked')?.value || 'later',
      ai_setup_mode: aiSetupMode,
    },
  };
  if (aiSetupMode === 'advanced') {
    body.ai_provider = document.getElementById('newProjProvider').value;
    body.ai_model = document.getElementById('newProjModel').value;
  }
  const createButton = document.getElementById('wizardCreateButton');
  createButton.disabled = true;
  createButton.textContent = '만드는 중...';
  const res = await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  createButton.disabled = false;
  createButton.textContent = '프로젝트 만들기';
  if (!res.ok) {
    document.getElementById('wizardValidation').textContent = data.error || '프로젝트를 만들지 못했습니다.';
    return;
  }
  closeModal('newProjectModal');
  await selectProject(data.id, true);
  showWorkspaceStage('overview');
  loadProjects();
}

async function deleteProject(id) {
  if (!confirm('정말 삭제하시겠습니까?')) return;
  await fetch(`/api/projects/${id}`, { method: 'DELETE' });
  if (currentProject?.id === id) {
    currentProject = null;
    currentOverview = null;
    localStorage.removeItem('lastProjectId');
    updateAppShell();
    showTab('projects');
  }
  loadProjects();
}

// ═══ 프로젝트 개요 ═══
async function loadOverview() {
  if (!currentProject) return;
  const statusIds = [
    'overviewCriteriaStatus',
    'overviewSubmissionStatus',
    'overviewGradingStatus',
    'overviewReviewStatus',
  ];
  statusIds.forEach(id => {
    const element = document.getElementById(id);
    if (element) element.textContent = '확인 중';
  });
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/overview`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '개요를 불러오지 못했습니다.');
    currentOverview = data;
    renderOverview(data);
  } catch (error) {
    document.getElementById('overviewNextReason').textContent = error.message;
    document.getElementById('overviewNextButton').textContent = '다시 시도';
  }
}

function renderOverview(data) {
  const project = data.project || {};
  document.getElementById('overviewWorkflow').textContent = project.workflow_label || '프로젝트';
  document.getElementById('overviewProjectName').textContent = project.name || currentProject.name;
  document.getElementById('overviewDescription').textContent = [
    project.target,
    project.assessment_name,
    project.description,
  ].filter(Boolean).join(' · ') || '준비 상태와 다음 작업을 확인합니다.';
  document.getElementById('overviewProgress').style.width = `${data.progress_percent || 0}%`;
  document.getElementById('overviewProgressText').textContent = `${data.progress_percent || 0}% 준비`;
  document.getElementById('overviewCriteriaStatus').textContent = data.criteria?.label || '확인 필요';
  document.getElementById('overviewSubmissionStatus').textContent = data.submissions?.label || '확인 필요';
  document.getElementById('overviewGradingStatus').textContent = data.grading?.label || '확인 필요';
  document.getElementById('overviewReviewStatus').textContent = data.review?.label || '확인 필요';
  document.getElementById('overviewNextReason').textContent = data.next_action?.reason || '다음 작업을 선택하세요.';
  document.getElementById('overviewNextButton').textContent = data.next_action?.label || '계속하기';

  const rounds = data.rounds || [];
  const roundContainer = document.getElementById('overviewRounds');
  if (!rounds.length) {
    roundContainer.innerHTML = '<div class="empty-state"><p>아직 실행한 채점 회차가 없습니다. 첫 회차를 실행하면 학생별 완료 상태가 여기에 표시됩니다.</p></div>';
    return;
  }
  roundContainer.innerHTML = rounds.map(round => `
    <div class="round-card">
      <div class="round-title"><strong>${round.id}회차</strong><span class="round-status status-${esc(round.status || 'legacy')}">${roundStatusLabel(round.status)}</span></div>
      <p>${round.completed_count}/${round.target_count || round.completed_count}명 성공 · 실패 ${round.failure_count || 0}명 · 회차 확인 ${round.approved_count}명 · 검토 표시 ${round.review_required_count}명</p>
      <p class="round-context-line">${round.model ? `${esc(round.provider)} · ${esc(round.model)} · ${criteriaVersionLabel(round)}` : '기존 회차 · 모델·기준 기록 없음'}</p>
    </div>
  `).join('');
}

function goToNextAction() {
  if (!currentOverview) {
    loadOverview();
    return;
  }
  showWorkspaceStage(currentOverview.next_action?.stage || 'overview');
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
  document.getElementById('cfgProjectType').value = currentProject.workflow_type || (currentProject.project_type === 'exam' ? 'exam' : 'report');
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
  const deliveryMode = document.getElementById('reportCriteriaDeliveryMode');
  if (deliveryMode) deliveryMode.value = currentProject.criteria_state?.delivery_mode || 'strict';
  await loadCriteriaVersions();
  await loadStandardizationWorkspace();
}

function changeProjectType(value) {
  if (!currentProject || !['report', 'competition', 'exam'].includes(value)) return;
  const nextProjectType = value === 'exam' ? 'exam' : 'report';
  if (currentProject.project_type !== nextProjectType) {
    currentProject.project_type = nextProjectType;
    currentProject.prompt_template = '';
    document.getElementById('cfgPrompt').value = '';
  }
  currentProject.workflow_type = value;
  updateProjectModeUI();
}

function updateProjectModeUI() {
  const isExam = currentProject?.project_type === 'exam';
  const reportCriteriaVersionCard = document.getElementById('reportCriteriaVersionCard');
  if (reportCriteriaVersionCard) reportCriteriaVersionCard.style.display = isExam ? 'none' : '';
  document.getElementById('reportRubricCard').style.display = isExam ? 'none' : '';
  document.getElementById('reportPromptCard').style.display = isExam ? 'none' : '';
  const reportStandardizationCard = document.getElementById('reportStandardizationCard');
  if (reportStandardizationCard) reportStandardizationCard.style.display = isExam ? 'none' : '';
  const examStandardizationCard = document.getElementById('examStandardizationCard');
  if (examStandardizationCard) examStandardizationCard.style.display = isExam ? '' : 'none';
  document.getElementById('examIntegratedMaterialsCard').style.display = isExam ? '' : 'none';
  document.getElementById('thApproval').style.display = isExam ? '' : 'none';
  const rankingCard = document.getElementById('competitionRankingCard');
  if (rankingCard) rankingCard.style.display = currentProject?.workflow_type === 'competition' ? '' : 'none';
  const sourceStep = document.getElementById('submissionSourceStep');
  if (sourceStep) sourceStep.textContent = isExam ? '3. 답안 가져오기' : '2. 답안 가져오기';
  updateAppShell();
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
    <details class="criteria-detail-editor">
      <summary>교사용 상세 기준 · AI용 압축 기준</summary>
      <div class="form-row">
        <div class="form-group"><label>필수 확인 요소</label><textarea rows="3" onchange="updateCriterionList(${ci},${i},'required_elements',this.value)">${esc((c.required_elements || []).join('\n'))}</textarea></div>
        <div class="form-group"><label>감점 규칙</label><textarea rows="3" onchange="updateCriterionList(${ci},${i},'deduction_rules',this.value)">${esc((c.deduction_rules || []).join('\n'))}</textarea></div>
        <div class="form-group"><label>예외·인정 기준</label><textarea rows="3" onchange="updateCriterionList(${ci},${i},'exceptions',this.value)">${esc((c.exceptions || []).join('\n'))}</textarea></div>
        <div class="form-group"><label>피드백 관점</label><textarea rows="3" onchange="currentProject.categories[${ci}].criteria[${i}].feedback_focus=this.value">${esc(c.feedback_focus || '')}</textarea></div>
      </div>
      <div class="form-group"><label>AI용 핵심 기준 — 한 줄에 하나</label><textarea rows="3" onchange="updateCriterionList(${ci},${i},'core_criteria',this.value)">${esc((c.core_criteria || []).join('\n'))}</textarea></div>
    </details>
  </div>`;
}

function updateCriterionList(categoryIndex, criterionIndex, field, value) {
  currentProject.categories[categoryIndex].criteria[criterionIndex][field] = value
    .split(/\r?\n/).map(item => item.trim()).filter(Boolean);
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
  cats[ci].criteria.push({
    id, name: '새 항목', description: '새 항목 설명',
    scale: [5, 4, 3, 2, 1],
    scale_labels: ['매우우수', '우수', '보통', '미흡', '매우미흡'],
    required_elements: [], deduction_rules: [], exceptions: [],
    feedback_focus: '', core_criteria: [],
  });
  renderRubric();
}

async function saveSettings(options = {}) {
  if (!currentProject) return alert('프로젝트를 먼저 선택하세요');
  currentProject.name = document.getElementById('cfgName').value;
  currentProject.description = document.getElementById('cfgDesc').value;
  currentProject.workflow_type = document.getElementById('cfgProjectType').value;
  currentProject.project_type = currentProject.workflow_type === 'exam' ? 'exam' : 'report';
  currentProject.ai_model = document.getElementById('cfgModel').value;
  currentProject.ai_provider = document.getElementById('cfgProvider').value;
  currentProject.temperature = parseFloat(document.getElementById('cfgTemp').value);
  currentProject.prompt_template = document.getElementById('cfgPrompt').value;
  if (!currentProject.criteria_state) currentProject.criteria_state = {};
  const reportDelivery = document.getElementById('reportCriteriaDeliveryMode');
  if (reportDelivery) currentProject.criteria_state.delivery_mode = reportDelivery.value;
  if (currentProject.project_type === 'exam' && currentProject.exam) {
    currentProject.exam.additional_instructions = document.getElementById('examAdditionalInstructions')?.value.trim() || '';
    currentProject.exam.grading_mode = document.getElementById('examGradingMode')?.value || currentProject.exam.grading_mode || 'strict';
    currentProject.exam.source_mode = document.getElementById('examSourceMode')?.value || 'auto';
    currentProject.exam.expected_question_count = Math.max(0, parseInt(document.getElementById('examExpectedQuestionCount')?.value) || 0);
  }
  const payload = {
    ...currentProject,
    criteria_change_source: pendingCriteriaSource || 'manual',
  };
  const res = await fetch(`/api/projects/${currentProject.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  if (!res.ok) {
    const err = await res.json();
    if (!options.silent) alert(err.error || '저장 실패');
    return false;
  }
  currentProject = await res.json();
  pendingCriteriaSource = null;
  await populateSettings();
  updateAppShell();
  if (!options.silent) alert('설정이 저장되었습니다');
  loadProjects();
  return true;
}

async function loadCriteriaVersions() {
  if (!currentProject) return;
  const res = await fetch(`/api/projects/${currentProject.id}/criteria-versions`);
  const data = await res.json();
  if (!res.ok) return;
  currentCriteriaVersions = data;
  currentProject.criteria_state = data.state;
  renderCriteriaVersionPanel('report', data);
  renderCriteriaVersionPanel('exam', data);
}

function renderCriteriaVersionPanel(prefix, data) {
  const status = document.getElementById(`${prefix}CriteriaStatus`);
  const validation = document.getElementById(`${prefix}CriteriaValidation`);
  const select = document.getElementById(`${prefix}CriteriaVersionSelect`);
  const approveButton = document.getElementById(`${prefix}CriteriaApproveButton`);
  if (!status || !validation || !select || !approveButton) return;

  const stateLabels = {
    empty: '기준 없음',
    unversioned: '기존 기준 · 버전 미저장',
    generated: 'AI 생성 초안 · 승인 필요',
    modified: '수정됨 · 새 버전 필요',
    draft: `v${data.state.active_version || '?'} 초안`,
    approved: `v${data.state.approved_version || data.state.active_version} 교사 승인`,
  };
  status.textContent = stateLabels[data.state.status] || '기준 확인 필요';
  status.className = `criteria-state-badge state-${data.state.status || 'empty'}`;

  const messages = [
    ...(data.validation.errors || []).map(message => `<div class="criteria-error">❌ ${esc(message)}</div>`),
    ...(data.validation.warnings || []).map(message => `<div class="criteria-warning">⚠️ ${esc(message)}</div>`),
  ];
  if (!messages.length && data.validation.scored_unit_count) {
    messages.push(`<div class="criteria-ok">✅ 채점 단위 ${data.validation.scored_unit_count}개 · 총 ${data.validation.total_max_score}점</div>`);
  }
  validation.innerHTML = messages.join('');

  const versions = [...(data.versions || [])].sort((a, b) => b.version - a.version);
  select.innerHTML = versions.length
    ? versions.map(version => `<option value="${version.version}" ${version.version === data.state.active_version ? 'selected' : ''}>v${version.version} · ${version.approved ? '승인' : '초안'} · ${criteriaSourceLabel(version.source)} · ${formatDateTime(version.created_at)}</option>`).join('')
    : '<option value="">저장된 버전 없음</option>';
  approveButton.disabled = !data.state.active_version
    || data.state.status === 'approved'
    || Boolean(data.validation.errors?.length);
}

function criteriaSourceLabel(source) {
  return ({
    manual: '교사 편집',
    official: '공식 기준',
    generated: 'AI 생성',
    synthesized: '선채점 기준화',
    compressed: 'AI 기준 압축',
    restored: '이전 버전 복원',
  })[source] || source || '기준';
}

async function saveCriteriaVersion() {
  if (!currentProject) return;
  if (!await saveSettings({ silent: true })) return;
  const source = currentProject.criteria_state?.source || 'manual';
  const res = await fetch(`/api/projects/${currentProject.id}/criteria-versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source }),
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '평가기준 버전 저장 실패');
  await selectProject(currentProject.id, true);
  alert(`평가기준 v${data.version.version} 초안을 저장했습니다.`);
}

async function approveActiveCriteria() {
  if (!currentProject) return;
  // 화면에 보이는 미저장 수정이 있으면 서버 상태에 먼저 반영한다.
  // 이때 기존 버전과 달라졌다면 active_version이 0으로 바뀌어 이전 버전의 오승인을 막는다.
  if (!await saveSettings({ silent: true })) return;
  if (!currentCriteriaVersions?.state?.active_version) {
    return alert('먼저 현재 기준을 새 버전으로 저장하세요.');
  }
  const version = currentCriteriaVersions.state.active_version;
  if (!confirm(`평가기준 v${version}을 교사 승인 기준으로 확정할까요?`)) return;
  const res = await fetch(`/api/projects/${currentProject.id}/criteria-versions/${version}/approve`, {
    method: 'POST',
  });
  const data = await res.json();
  if (!res.ok) {
    const details = data.validation?.errors?.join('\n');
    return alert([data.error || '승인 실패', details].filter(Boolean).join('\n'));
  }
  await selectProject(currentProject.id, true);
}

async function restoreSelectedCriteria(prefix) {
  if (!currentProject) return;
  const version = parseInt(document.getElementById(`${prefix}CriteriaVersionSelect`)?.value);
  if (!version) return alert('복원할 버전이 없습니다.');
  if (!confirm(`평가기준 v${version}으로 되돌릴까요? 현재 편집 중인 기준은 새 버전으로 저장하지 않았다면 사라집니다.`)) return;
  const res = await fetch(`/api/projects/${currentProject.id}/criteria-versions/${version}/restore`, {
    method: 'POST',
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '버전 복원 실패');
  currentProject = data.project;
  await populateSettings();
  updateAppShell();
}

async function previewCriteriaPrompt() {
  if (!await saveSettings({ silent: true })) return;
  const preview = document.getElementById('examCriteriaPromptPreview');
  if (!preview) return;
  preview.textContent = currentProject.prompt_template || '생성된 AI 전달 기준이 없습니다.';
  preview.style.display = preview.style.display === 'none' ? '' : 'none';
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
  const students = currentProject.submissions?.students || currentProject.exam.students || [];
  const rosterInput = document.getElementById('rosterInput');
  if (rosterInput) rosterInput.value = students.map(s => `${s.number}, ${s.name || ''}`).join('\n');
  const rosterStatus = document.getElementById('rosterStatus');
  if (rosterStatus) rosterStatus.textContent = '';
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
  renderSplitOutput('', false);
  renderExamQuestions();
}

function renderExamQuestions() {
  const el = document.getElementById('examQuestionEditor');
  const questions = currentProject?.exam?.questions || [];
  if (!questions.length) {
    el.innerHTML = '<div class="empty-state"><p>문제지를 업로드하여 기준을 생성하거나 문항을 직접 추가하세요.</p></div>';
    return;
  }
  const indexed = questions.map((question, index) => ({ question, index }));
  const ordered = [];
  for (const item of indexed.filter(item => !item.question.parent_id)) {
    ordered.push(item);
    ordered.push(...indexed
      .filter(child => child.question.parent_id === item.question.id)
      .sort((a, b) => (a.question.sub_index || 0) - (b.question.sub_index || 0)));
  }
  const known = new Set(ordered.map(item => item.index));
  ordered.push(...indexed.filter(item => !known.has(item.index)));

  el.innerHTML = ordered.map(({ question: q, index }) => {
    const children = indexed
      .filter(item => item.question.parent_id === q.id)
      .sort((a, b) => (a.question.sub_index || 0) - (b.question.sub_index || 0));
    const isGroup = children.length > 0;
    const isChild = Boolean(q.parent_id);
    const elementText = (q.scoring_elements || []).map(e => `${e.points}|${e.required === false ? '선택' : '필수'}|${e.description}`).join('\n');
    const points = (q.scoring_elements || []).reduce((sum, e) => sum + Number(e.points || 0), 0);
    const pointColor = points > Number(q.max_score || 0) ? 'var(--danger)' : 'var(--text2)';
    if (isGroup) {
      const childTotal = children.reduce((sum, item) => sum + Number(item.question.max_score || 0), 0);
      const mismatch = childTotal !== Number(q.max_score || 0);
      return `<div class="card exam-question-card exam-question-group">
        <div class="exam-question-header">
          <span class="question-kind">대문항 묶음</span>
          <input value="${esc(q.number)}" style="max-width:90px" aria-label="대문항 번호" onchange="updateExamQuestion(${index},'number',this.value)">
          <input type="number" min="1" value="${q.max_score || 1}" style="max-width:100px" aria-label="대문항 배점" onchange="updateExamQuestion(${index},'max_score',this.value)">
          <span class="score-check ${mismatch ? 'error' : 'success'}">소문항 합 ${childTotal}/${q.max_score || 1}${mismatch ? ' · 수정 필요' : ''}</span>
          <button class="btn btn-secondary btn-sm" onclick="addExamSubQuestion(${index})">+ 소문항</button>
          <button class="btn-icon" style="margin-left:auto" onclick="removeExamQuestion(${index})">🗑</button>
        </div>
        <div class="form-group"><label>공통 지문·조건</label><textarea rows="3" onchange="updateExamQuestion(${index},'question_text',this.value)">${esc(q.question_text || '')}</textarea></div>
        <div class="form-group"><label>교사 메모 — AI에는 전달하지 않음</label><textarea rows="2" onchange="updateExamQuestion(${index},'teacher_notes',this.value)">${esc(q.teacher_notes || '')}</textarea></div>
      </div>`;
    }

    return `<div class="card exam-question-card ${isChild ? 'exam-sub-question' : ''}">
      <div class="exam-question-header">
        <span class="question-kind">${isChild ? '소문항' : '채점 문항'}</span>
        <input value="${esc(q.number)}" style="max-width:80px" aria-label="문항 번호" onchange="updateExamQuestion(${index},'number',this.value)">
        <input type="number" min="1" value="${q.max_score || 1}" style="max-width:100px" aria-label="배점" onchange="updateExamQuestion(${index},'max_score',this.value)">
        <span class="score-check" style="color:${pointColor}">부분점 합 ${points}/${q.max_score || 1}</span>
        <select aria-label="답안 유형" onchange="updateExamQuestion(${index},'answer_type',this.value)">
          <option value="short" ${q.answer_type === 'short' ? 'selected' : ''}>단답형</option>
          <option value="text" ${!q.answer_type || q.answer_type === 'text' ? 'selected' : ''}>문장 서술형</option>
          <option value="formula" ${q.answer_type === 'formula' ? 'selected' : ''}>수식·계산형</option>
          <option value="diagram" ${q.answer_type === 'diagram' ? 'selected' : ''}>그래프·도식형</option>
          <option value="mixed" ${q.answer_type === 'mixed' ? 'selected' : ''}>복합형</option>
        </select>
        <select aria-label="문항 채점 방식" onchange="updateExamQuestion(${index},'grading_mode',this.value)">
          <option value="inherit" ${!q.grading_mode || q.grading_mode === 'inherit' ? 'selected' : ''}>전체 설정 따름</option>
          <option value="autonomous" ${q.grading_mode === 'autonomous' ? 'selected' : ''}>자율 선채점</option>
          <option value="core" ${q.grading_mode === 'core' ? 'selected' : ''}>핵심 기준</option>
          <option value="strict" ${q.grading_mode === 'strict' ? 'selected' : ''}>공식 기준 엄격</option>
        </select>
        ${!isChild ? `<button class="btn btn-secondary btn-sm" onclick="addExamSubQuestion(${index})">소문항으로 나누기</button>` : ''}
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
      <div class="form-group"><label>교사 메모 — AI에는 전달하지 않음</label><textarea rows="2" onchange="updateExamQuestion(${index},'teacher_notes',this.value)">${esc(q.teacher_notes || '')}</textarea></div>
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
  const questions = currentProject.exam.questions;
  let index = questions.length + 1;
  while (questions.some(question => question.id === `q${index}`)) index += 1;
  currentProject.exam.questions.push({
    id: `q${index}`, number: String(index), question_text: '', max_score: 5,
    model_answer: '', scoring_elements: [], accepted_answers: [], common_errors: [],
    core_criteria: [], parent_id: '', sub_index: 0, answer_type: 'text',
    grading_mode: 'inherit', teacher_notes: '',
  });
  renderExamQuestions();
}

function addExamSubQuestion(parentIndex) {
  const questions = currentProject.exam.questions;
  const parent = questions[parentIndex];
  if (!parent) return;
  const children = questions.filter(question => question.parent_id === parent.id);
  const subIndex = children.length + 1;
  let id = `${parent.id}_s${subIndex}`;
  let suffix = subIndex;
  while (questions.some(question => question.id === id)) id = `${parent.id}_s${++suffix}`;

  const firstChild = children.length === 0;
  const child = {
    id,
    number: `${parent.number}-(${subIndex})`,
    question_text: firstChild ? parent.question_text : '',
    max_score: firstChild ? Number(parent.max_score || 1) : 1,
    model_answer: firstChild ? (parent.model_answer || '') : '',
    scoring_elements: firstChild
      ? (parent.scoring_elements || []).map(element => ({ ...element }))
      : [],
    accepted_answers: firstChild ? [...(parent.accepted_answers || [])] : [],
    common_errors: firstChild ? [...(parent.common_errors || [])] : [],
    core_criteria: firstChild ? [...(parent.core_criteria || [])] : [],
    parent_id: parent.id,
    sub_index: subIndex,
    answer_type: firstChild ? (parent.answer_type || 'text') : 'text',
    grading_mode: firstChild ? (parent.grading_mode || 'inherit') : 'inherit',
    teacher_notes: '',
  };
  if (firstChild) {
    parent.model_answer = '';
    parent.scoring_elements = [];
    parent.accepted_answers = [];
    parent.common_errors = [];
    parent.core_criteria = [];
    parent.grading_mode = 'inherit';
  }
  questions.push(child);
  renderExamQuestions();
}

function removeExamQuestion(index) {
  const questions = currentProject.exam.questions;
  const question = questions[index];
  if (!question) return;
  const childCount = questions.filter(item => item.parent_id === question.id).length;
  if (childCount && !confirm(`${question.number}번 대문항과 소문항 ${childCount}개를 모두 삭제할까요?`)) return;
  currentProject.exam.questions = questions.filter(
    item => item.id !== question.id && item.parent_id !== question.id
  );
  renderExamQuestions();
}

let currentStandardizationWorkspace = null;
let currentStandardizationSession = null;
let currentStandardizationSummary = null;

function standardizationPrefix() {
  return currentProject?.project_type === 'exam' ? 'exam' : 'report';
}

function standardizationElement(suffix) {
  return document.getElementById(`${standardizationPrefix()}Standardization${suffix}`);
}

function standardizationStatusLabel(status) {
  return ({
    draft: '교사 검토 중',
    approved: '교사 승인 완료',
    discarded: '폐기됨',
  })[status] || '초안 없음';
}

function standardizationRoundSignature(round) {
  return [
    round.criteria_fingerprint || '',
    round.criteria_version || 0,
    round.provider || '',
    round.model || '',
  ].join('|');
}

function defaultStandardizationRounds(rounds) {
  if (!rounds.length) return [];
  const latest = rounds[rounds.length - 1];
  const signature = standardizationRoundSignature(latest);
  return rounds
    .filter(round => standardizationRoundSignature(round) === signature)
    .slice(-2)
    .map(round => round.id);
}

async function loadStandardizationWorkspace(options = {}) {
  if (!currentProject) return;
  const roundsElement = standardizationElement('Rounds');
  if (!roundsElement) return;
  try {
    const response = await fetch(`/api/projects/${currentProject.id}/standardizations`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '기준화 작업을 불러오지 못했습니다.');
    currentStandardizationWorkspace = data;
    renderStandardizationWorkspace(options);
  } catch (error) {
    roundsElement.innerHTML = `<div class="criteria-error">${esc(error.message)}</div>`;
  }
}

function renderStandardizationWorkspace(options = {}) {
  const workspace = currentStandardizationWorkspace || { rounds: [], sessions: [] };
  const rounds = workspace.rounds || [];
  const selected = new Set(
    options.roundIds
    || currentStandardizationSession?.source_round_ids
    || defaultStandardizationRounds(rounds)
  );
  const roundsElement = standardizationElement('Rounds');
  roundsElement.innerHTML = rounds.length
    ? rounds.map(round => `<label class="standardization-round-option">
        <input type="checkbox" value="${round.id}" ${selected.has(round.id) ? 'checked' : ''}>
        <span>
          <strong>${round.id}회차 · ${round.completed_count}/${round.target_count || round.completed_count}명</strong>
          <small>${esc(round.provider || '이전 방식')} · ${esc(round.model || '모델 기록 없음')} · 기준 v${round.criteria_version || '미저장'}</small>
        </span>
      </label>`).join('')
    : '<div class="empty-state compact"><p>완료된 선채점 회차가 없습니다. 먼저 AI 채점을 실행하세요.</p></div>';

  const sessions = workspace.sessions || [];
  const sessionSelect = standardizationElement('Session');
  sessionSelect.innerHTML = sessions.length
    ? sessions.map(session => `<option value="${esc(session.id)}">${
        formatDateTime(session.created_at)} · ${standardizationStatusLabel(session.status)} · ${
        (session.source_round_ids || []).join('·')}회차${session.approved_version ? ` · 기준 v${session.approved_version}` : ''}</option>`).join('')
    : '<option value="">저장된 기준화 작업 없음</option>';
  const requestedSessionId = options.sessionId
    || currentStandardizationSession?.id
    || sessions.find(session => session.status === 'draft')?.id
    || sessions[0]?.id
    || '';
  if (requestedSessionId && sessions.some(session => session.id === requestedSessionId)) {
    sessionSelect.value = requestedSessionId;
    if (!currentStandardizationSession || currentStandardizationSession.id !== requestedSessionId) {
      selectStandardizationSession(requestedSessionId);
      return;
    }
  } else {
    currentStandardizationSession = null;
    currentStandardizationSummary = null;
    renderStandardizationSession();
  }

  const generateButton = standardizationElement('Generate');
  if (generateButton) generateButton.disabled = !rounds.length;
  const state = standardizationElement('State');
  state.textContent = sessions.length
    ? `${sessions.length}개 작업 보존`
    : (rounds.length ? '초안 생성 가능' : '선채점 필요');
  state.className = `criteria-state-badge ${rounds.length ? 'state-draft' : 'state-empty'}`;
}

async function selectStandardizationSession(sessionId) {
  if (!currentProject || !sessionId) {
    currentStandardizationSession = null;
    currentStandardizationSummary = null;
    renderStandardizationSession();
    return;
  }
  const status = standardizationElement('Status');
  status.textContent = '저장된 기준화 초안을 불러오는 중...';
  const response = await fetch(
    `/api/projects/${currentProject.id}/standardizations/${encodeURIComponent(sessionId)}`
  );
  const data = await response.json();
  if (!response.ok) {
    status.textContent = `❌ ${data.error || '초안을 불러오지 못했습니다.'}`;
    return;
  }
  currentStandardizationSession = data.session;
  currentStandardizationSummary = data.summary;
  const sessionSelect = standardizationElement('Session');
  if (sessionSelect) sessionSelect.value = sessionId;
  renderStandardizationSession();
}

function selectedStandardizationRounds() {
  return [...standardizationElement('Rounds').querySelectorAll('input[type="checkbox"]:checked')]
    .map(input => Number(input.value))
    .filter(Number.isFinite);
}

async function generateStandardization() {
  if (!currentProject) return;
  const roundIds = selectedStandardizationRounds();
  if (!roundIds.length) return alert('기준화에 사용할 완료 회차를 선택하세요.');
  const costNote = '기준화 초안 생성에는 AI 요청 1회가 사용됩니다. 실제 평가기준은 교사 승인 전까지 바뀌지 않습니다.';
  if (!confirm(`${roundIds.join('·')}회차를 함께 분석합니다.\n\n${costNote}\n\n계속할까요?`)) return;
  const status = standardizationElement('Status');
  const button = standardizationElement('Generate');
  button.disabled = true;
  status.textContent = '⏳ 답안 유형과 채점 차이를 분석해 기준화 초안을 만드는 중입니다...';
  try {
    const response = await fetch(`/api/projects/${currentProject.id}/standardizations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        round_ids: roundIds,
        teacher_instruction: standardizationElement('Instruction').value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '기준화 초안 생성 실패');
    currentStandardizationSession = data.session;
    currentStandardizationSummary = data.summary;
    status.textContent = `✅ ${data.session.student_count}명 · ${data.session.observation_count}개 채점 근거로 초안을 만들었습니다. 교사가 내용을 확인하세요.`;
    await loadStandardizationWorkspace({ sessionId: data.session.id, roundIds });
  } catch (error) {
    status.textContent = `❌ ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function standardizationEvidenceBadge(strength) {
  const label = ({ strong: '근거 충분', moderate: '근거 보통', weak: '근거 약함' })[strength] || '근거 확인';
  return `<span class="standardization-evidence evidence-${esc(strength || 'weak')}">${label}</span>`;
}

function standardizationListText(values) {
  return (values || []).join('\n');
}

function standardizationScoringText(values) {
  return (values || [])
    .map(value => `${value.points}|${value.required === false ? '선택' : '필수'}|${value.description}`)
    .join('\n');
}

function renderStandardizationSession() {
  const session = currentStandardizationSession;
  const editor = standardizationElement('Draft');
  const validation = standardizationElement('Validation');
  const saveButton = standardizationElement('Save');
  const approveButton = standardizationElement('Approve');
  const discardButton = standardizationElement('Discard');
  const sample = standardizationElement('Sample');
  if (!session) {
    editor.innerHTML = '<div class="empty-state"><p>선채점 회차를 선택해 기준화 초안을 만드세요.</p></div>';
    validation.innerHTML = '';
    saveButton.disabled = true;
    approveButton.disabled = true;
    discardButton.disabled = true;
    sample.style.display = 'none';
    return;
  }

  const isDraft = session.status === 'draft';
  const draft = session.draft || {};
  const items = currentProject.project_type === 'exam'
    ? (draft.questions || [])
    : (draft.criteria || []);
  const overall = draft.overall_note
    ? `<div class="info-callout standardization-overall"><strong>AI 종합 메모</strong><p>${esc(draft.overall_note)}</p></div>`
    : '';
  editor.innerHTML = overall + items.map(item => (
    currentProject.project_type === 'exam'
      ? renderExamStandardizationItem(item, isDraft)
      : renderReportStandardizationItem(item, isDraft)
  )).join('');

  const draftValidation = session.draft_validation || {};
  const warningMessages = [
    ...(currentStandardizationSummary?.criteria_changed
      ? ['<div class="criteria-error">❌ 이 초안을 만든 뒤 현재 평가기준이 바뀌었습니다. 현재 기준으로 새 초안을 만들거나 이전 기준 버전을 복원하세요.</div>']
      : []),
    ...(session.warnings || []).map(message => `<div class="criteria-warning">⚠️ ${esc(message)}</div>`),
    ...(draftValidation.errors || []).map(message => `<div class="criteria-error">❌ ${esc(message)}</div>`),
    ...(draftValidation.warnings || []).map(message => `<div class="criteria-warning">⚠️ ${esc(message)}</div>`),
  ];
  if (!warningMessages.length) {
    warningMessages.push(`<div class="criteria-ok">✅ ${session.source_round_ids.join('·')}회차 · ${session.student_count}명 · 채점 근거 ${session.observation_count}건</div>`);
  }
  validation.innerHTML = warningMessages.join('');
  const criteriaChanged = Boolean(currentStandardizationSummary?.criteria_changed);
  saveButton.disabled = !isDraft || criteriaChanged;
  approveButton.disabled = !isDraft || criteriaChanged || Boolean(draftValidation.errors?.length);
  discardButton.disabled = !isDraft;
  standardizationElement('State').textContent = standardizationStatusLabel(session.status)
    + (session.approved_version ? ` · 기준 v${session.approved_version}` : '');
  standardizationElement('State').className = `criteria-state-badge state-${session.status === 'approved' ? 'approved' : (session.status === 'draft' ? 'draft' : 'modified')}`;
  standardizationElement('TeacherNote').value = session.teacher_note || '';
  sample.style.display = session.status === 'approved' ? '' : 'none';
  if (session.status === 'approved') {
    const recommendations = session.recommended_sample_teams || [];
    const teamInput = standardizationElement('SampleTeams');
    teamInput.value = recommendations.map(item => item.team_number).join(', ');
    renderStandardizationComparison(currentStandardizationSummary?.comparison);
  }
}

function disabledAttribute(editable) {
  return editable ? '' : 'disabled';
}

function renderExamStandardizationItem(item, editable) {
  const disabled = disabledAttribute(editable);
  return `<div class="standardization-draft-item" data-item-id="${esc(item.id)}" data-kind="exam">
    <div class="standardization-item-heading">
      <div><strong>${esc(item.number)}번 · ${item.max_score}점</strong><small>${esc(item.question_text || '')}</small></div>
      ${standardizationEvidenceBadge(item.evidence_strength)}
    </div>
    ${item.change_summary ? `<p class="standardization-change"><strong>제안 변화:</strong> ${esc(item.change_summary)}</p>` : ''}
    <div class="form-group"><label>모범 답안</label><textarea data-field="model_answer" rows="3" ${disabled}>${esc(item.model_answer || '')}</textarea></div>
    <div class="standardization-grid">
      <div class="form-group"><label>부분점 기준 — 점수|필수/선택|설명</label><textarea data-field="scoring_elements" rows="5" ${disabled}>${esc(standardizationScoringText(item.scoring_elements))}</textarea></div>
      <div class="form-group"><label>AI용 핵심 기준 — 한 줄에 하나</label><textarea data-field="core_criteria" rows="5" ${disabled}>${esc(standardizationListText(item.core_criteria))}</textarea></div>
      <div class="form-group"><label>정답 인정 표현</label><textarea data-field="accepted_answers" rows="4" ${disabled}>${esc(standardizationListText(item.accepted_answers))}</textarea></div>
      <div class="form-group"><label>감점·오답 사례</label><textarea data-field="common_errors" rows="4" ${disabled}>${esc(standardizationListText(item.common_errors))}</textarea></div>
      <div class="form-group"><label>경계 사례 — 자동 인정하지 않고 교사 확인</label><textarea data-field="boundary_cases" rows="4" ${disabled}>${esc(standardizationListText(item.boundary_cases))}</textarea></div>
      <div class="form-group"><label>교사 메모</label><textarea data-field="teacher_notes" rows="4" ${disabled}>${esc(item.teacher_notes || '')}</textarea></div>
    </div>
    ${item.rationale ? `<details><summary>AI 제안 근거</summary><p>${esc(item.rationale)}</p></details>` : ''}
  </div>`;
}

function renderReportStandardizationItem(item, editable) {
  const disabled = disabledAttribute(editable);
  return `<div class="standardization-draft-item" data-item-id="${esc(item.id)}" data-kind="report">
    <div class="standardization-item-heading">
      <div><strong>${esc(item.category)} · ${esc(item.name)}</strong><small>기존 척도 ${esc((item.scale || []).join(' / '))}점 유지</small></div>
      ${standardizationEvidenceBadge(item.evidence_strength)}
    </div>
    ${item.change_summary ? `<p class="standardization-change"><strong>제안 변화:</strong> ${esc(item.change_summary)}</p>` : ''}
    <div class="form-group"><label>상세 평가 설명</label><textarea data-field="description" rows="3" ${disabled}>${esc(item.description || '')}</textarea></div>
    <div class="standardization-grid">
      <div class="form-group"><label>필수 확인 요소</label><textarea data-field="required_elements" rows="4" ${disabled}>${esc(standardizationListText(item.required_elements))}</textarea></div>
      <div class="form-group"><label>감점 규칙</label><textarea data-field="deduction_rules" rows="4" ${disabled}>${esc(standardizationListText(item.deduction_rules))}</textarea></div>
      <div class="form-group"><label>예외·인정 기준</label><textarea data-field="exceptions" rows="4" ${disabled}>${esc(standardizationListText(item.exceptions))}</textarea></div>
      <div class="form-group"><label>AI용 핵심 기준</label><textarea data-field="core_criteria" rows="4" ${disabled}>${esc(standardizationListText(item.core_criteria))}</textarea></div>
      <div class="form-group"><label>경계 사례 — 자동 인정하지 않고 교사 확인</label><textarea data-field="boundary_cases" rows="4" ${disabled}>${esc(standardizationListText(item.boundary_cases))}</textarea></div>
      <div class="form-group"><label>피드백 관점</label><textarea data-field="feedback_focus" rows="4" ${disabled}>${esc(item.feedback_focus || '')}</textarea></div>
    </div>
    ${item.rationale ? `<details><summary>AI 제안 근거</summary><p>${esc(item.rationale)}</p></details>` : ''}
  </div>`;
}

function standardizationLines(value) {
  return value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

function parseStandardizationScoring(value) {
  return standardizationLines(value).map(line => {
    const parts = line.split('|');
    const points = Number(parts.shift());
    const requirement = (parts.shift() || '필수').trim();
    const description = parts.join('|').trim();
    return {
      points,
      required: !['선택', 'optional', 'false'].includes(requirement.toLowerCase()),
      description,
    };
  }).filter(item => Number.isInteger(item.points) && item.points > 0 && item.description);
}

function collectStandardizationDraft() {
  if (!currentStandardizationSession) return null;
  const draft = JSON.parse(JSON.stringify(currentStandardizationSession.draft || {}));
  const key = currentProject.project_type === 'exam' ? 'questions' : 'criteria';
  const byId = Object.fromEntries((draft[key] || []).map(item => [item.id, item]));
  standardizationElement('Draft').querySelectorAll('.standardization-draft-item').forEach(element => {
    const item = byId[element.dataset.itemId];
    if (!item) return;
    element.querySelectorAll('[data-field]').forEach(input => {
      const field = input.dataset.field;
      if (field === 'scoring_elements') item[field] = parseStandardizationScoring(input.value);
      else if (['core_criteria', 'accepted_answers', 'common_errors', 'boundary_cases',
        'required_elements', 'deduction_rules', 'exceptions'].includes(field)) {
        item[field] = standardizationLines(input.value);
      } else item[field] = input.value.trim();
    });
  });
  return draft;
}

async function saveStandardizationDraft(options = {}) {
  if (!currentProject || currentStandardizationSession?.status !== 'draft') return false;
  const draft = collectStandardizationDraft();
  const response = await fetch(
    `/api/projects/${currentProject.id}/standardizations/${encodeURIComponent(currentStandardizationSession.id)}/draft`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ draft }),
    }
  );
  const data = await response.json();
  if (!response.ok) {
    if (!options.silent) alert(data.error || '기준화 초안 저장 실패');
    return false;
  }
  currentStandardizationSession = data.session;
  currentStandardizationSummary = data.summary;
  renderStandardizationSession();
  if (!options.silent) standardizationElement('Status').textContent = '✅ 수정한 기준화 초안을 저장했습니다.';
  return true;
}

async function approveStandardization() {
  if (!currentProject || currentStandardizationSession?.status !== 'draft') return;
  const draft = collectStandardizationDraft();
  const versionText = currentProject.criteria_state?.approved_version
    ? `현재 승인 기준 v${currentProject.criteria_state.approved_version}은 그대로 보존됩니다.`
    : '현재 기준도 버전 기록에 보존됩니다.';
  if (!confirm(
    `이 기준화 초안을 교사 승인하고 새 평가기준 버전으로 적용할까요?\n\n${versionText}\n승인 뒤에는 추천 표본만 먼저 재채점합니다. 전원 재채점은 자동으로 실행되지 않습니다.`
  )) return;
  const status = standardizationElement('Status');
  status.textContent = '⏳ 초안을 검증하고 새 승인 기준 버전으로 저장하는 중...';
  const response = await fetch(
    `/api/projects/${currentProject.id}/standardizations/${encodeURIComponent(currentStandardizationSession.id)}/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        draft,
        delivery_mode: standardizationElement('Delivery').value,
        teacher_note: standardizationElement('TeacherNote').value.trim(),
      }),
    }
  );
  const data = await response.json();
  if (!response.ok) {
    const details = data.validation?.errors?.join('\n');
    status.textContent = `❌ ${data.error || '기준화 승인 실패'}`;
    if (details) alert(details);
    return;
  }
  currentProject = data.project;
  currentStandardizationSession = data.session;
  currentStandardizationSummary = data.summary;
  status.textContent = `✅ 기준 v${data.version.version}으로 교사 승인했습니다. 전체 재채점 전에 추천 표본을 확인하세요.`;
  await populateSettings();
}

async function discardStandardization() {
  if (!currentProject || currentStandardizationSession?.status !== 'draft') return;
  if (!confirm('이 기준화 초안을 폐기할까요? 선채점 회차와 기존 평가기준은 삭제되지 않습니다.')) return;
  const response = await fetch(
    `/api/projects/${currentProject.id}/standardizations/${encodeURIComponent(currentStandardizationSession.id)}/discard`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }
  );
  const data = await response.json();
  if (!response.ok) return alert(data.error || '기준화 초안 폐기 실패');
  currentStandardizationSession = data.session;
  currentStandardizationSummary = data.summary;
  await loadStandardizationWorkspace({ sessionId: data.session.id });
}

async function startStandardizationSample() {
  if (!currentProject || currentStandardizationSession?.status !== 'approved') return;
  const numbers = standardizationElement('SampleTeams').value
    .split(',')
    .map(value => Number(value.trim()))
    .filter(value => Number.isInteger(value) && value > 0);
  if (!numbers.length) return alert('표본 재채점할 학생 번호를 입력하세요.');
  const started = await startGrading(numbers, {
    mode: 'new',
    new_round: true,
    repeat_count: 1,
    start_from: 1,
  });
  if (started === true) showWorkspaceStage('grading');
}

function standardizationMetric(value) {
  return value == null ? '측정 불가' : `${value}점`;
}

function renderStandardizationComparison(comparison) {
  const element = standardizationElement('Comparison');
  if (!comparison || comparison.status !== 'ready') {
    const reason = comparison?.verdict_reasons?.[0]
      || '추천 표본을 새 승인 기준으로 채점하면 이곳에 변경 전후 비교가 표시됩니다.';
    element.innerHTML = `<div class="info-callout"><strong>표본 검증 대기</strong><p>${esc(reason)}</p></div>`;
    return;
  }
  const verdictLabel = ({
    improved: '개선 신호',
    mixed: '혼합 결과',
    worse: '재검토 필요',
    insufficient: '측정 자료 부족',
  })[comparison.verdict] || '결과 확인';
  const before = comparison.summary?.before || {};
  const after = comparison.summary?.after || {};
  element.innerHTML = `
    <div class="standardization-comparison-head verdict-${esc(comparison.verdict)}">
      <div><span>표본 ${comparison.summary.student_count}명 · 기준 v${comparison.approved_version}</span><strong>${verdictLabel}</strong></div>
      <small>기존 ${comparison.baseline_round_ids.join('·')}회차 → 표본 ${comparison.validation_round_ids.join('·')}회차</small>
    </div>
    <div class="standardization-metrics">
      <div><span>수동 점수 평균 오차</span><strong>${standardizationMetric(before.manual_mae)} → ${standardizationMetric(after.manual_mae)}</strong></div>
      <div><span>회차 간 평균 표준편차</span><strong>${standardizationMetric(before.mean_within_student_std)} → ${standardizationMetric(after.mean_within_student_std)}</strong></div>
      <div><span>평균 점수 변화</span><strong>${comparison.summary.mean_score_delta == null ? '측정 불가' : `${comparison.summary.mean_score_delta > 0 ? '+' : ''}${comparison.summary.mean_score_delta}점`}</strong></div>
    </div>
    <div class="standardization-verdict-reasons">${(comparison.verdict_reasons || []).map(reason => `<p>• ${esc(reason)}</p>`).join('')}</div>
    <details>
      <summary>학생별·항목별 변화 보기</summary>
      <div class="table-wrap"><table><thead><tr><th>번호</th><th>변경 전</th><th>변경 후</th><th>차이</th><th>수동</th></tr></thead>
      <tbody>${(comparison.students || []).map(student => `<tr>
        <td>${student.team_number}번</td><td>${student.before}</td><td>${student.after}</td>
        <td>${student.delta > 0 ? '+' : ''}${student.delta}</td><td>${student.manual_score ?? '-'}</td>
      </tr>`).join('')}</tbody></table></div>
      <div class="standardization-item-comparison">${(comparison.items || []).map(item => `<div>
        <strong>${esc(item.label)}</strong>
        <span>수동 오차 ${standardizationMetric(item.before.manual_mae)} → ${standardizationMetric(item.after.manual_mae)}</span>
        <span>회차 편차 ${standardizationMetric(item.before.mean_within_student_std)} → ${standardizationMetric(item.after.mean_within_student_std)}</span>
      </div>`).join('')}</div>
    </details>`;
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
    await loadCriteriaVersions();
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
    await loadCriteriaVersions();
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
    await loadCriteriaVersions();
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
  await loadCriteriaVersions();
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
  const input = document.getElementById('rosterInput');
  let nextNumber = 1;
  return (input?.value || '').split(/\r?\n/).map(line => {
    const value = line.trim();
    if (!value) return null;
    const match = value.match(/^(\d+)\s*[,\t.\-]?\s*(.*)$/);
    if (match) {
      const number = parseInt(match[1]);
      nextNumber = Math.max(nextNumber, number + 1);
      return { number, name: match[2].trim() || `학생 ${match[1]}` };
    }
    return { number: nextNumber++, name: value };
  }).filter(Boolean);
}

async function saveRoster(options = {}) {
  if (!currentProject) throw new Error('프로젝트를 먼저 선택하세요.');
  const students = parseStudentLines();
  if (options.requireStudents && !students.length) throw new Error('학생 명렬을 입력하세요.');
  const status = document.getElementById('rosterStatus');
  if (status) status.textContent = '저장 중...';
  const res = await fetch(`/api/projects/${currentProject.id}/roster`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ students }),
  });
  const data = await res.json();
  if (!res.ok) {
    if (status) status.textContent = `❌ ${data.error || '명렬 저장 실패'}`;
    throw new Error(data.error || '명렬 저장 실패');
  }
  if (!currentProject.submissions) currentProject.submissions = {};
  currentProject.submissions.students = data.students;
  if (currentProject.project_type === 'exam') currentProject.exam.students = data.students;
  if (status) status.textContent = `✅ ${data.students.length}명 저장`;
  renderSubmissionStatus(data.status);
  return data.students;
}

async function saveRosterFromUI() {
  try {
    await saveRoster();
  } catch (error) {
    alert(error.message);
  }
}

async function saveExamStudents() {
  return saveRoster({ requireStudents: true });
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
  if (data.output_dir) renderSplitOutput(data.output_dir);
}

function renderSplitOutput(outputDir, exists = Boolean(outputDir), fileCount = 0) {
  const container = document.getElementById('examSplitOutput');
  const path = document.getElementById('examSplitOutputPath');
  if (!container || !path) return;
  if (!outputDir || !exists) {
    container.style.display = 'none';
    path.textContent = '';
    return;
  }
  container.style.display = '';
  path.textContent = fileCount ? `${outputDir} · PDF ${fileCount}개` : outputDir;
  container.dataset.path = outputDir;
}

function openSplitOutputFolder() {
  const container = document.getElementById('examSplitOutput');
  const path = container?.dataset.path;
  if (path) openFile(path);
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
    await loadSubmissionStatus();
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
      body: JSON.stringify({
        categories: currentProject.categories,
        criteria_change_source: pendingCriteriaSource || 'manual',
      }),
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
    pendingCriteriaSource = 'official';
    
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
    pendingCriteriaSource = 'generated';
    
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
  await loadSubmissionStatus();
}

async function loadSubmissionStatus() {
  if (!currentProject) return;
  const res = await fetch(`/api/projects/${currentProject.id}/submissions`);
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('materialsList').innerHTML = `<div class="empty-state"><p>${esc(data.error || '답안 연결 상태를 불러오지 못했습니다.')}</p></div>`;
    return;
  }
  renderSubmissionStatus(data);
}

function renderSubmissionStatus(data) {
  currentSubmissionStatus = data;
  submissionFilesByIndex = [];
  const entries = data?.entries || [];
  const summary = data?.summary || {};
  const summaryEl = document.getElementById('submissionSummary');
  const listEl = document.getElementById('materialsList');
  const rosterStatus = document.getElementById('rosterStatus');
  const roster = data?.roster || [];

  if (!currentProject.submissions) currentProject.submissions = {};
  currentProject.submissions.students = roster;
  if (currentProject.project_type === 'exam') currentProject.exam.students = roster;
  if (rosterStatus && data.roster_source === 'files') {
    rosterStatus.textContent = '파일명에서 임시 명렬을 찾았습니다. 확인 후 명렬로 저장하세요.';
  }
  renderSplitOutput(data?.split?.output_dir, data?.split?.exists, data?.split?.file_count || 0);

  if (summaryEl) {
    summaryEl.innerHTML = `
      <span class="badge badge-primary">명렬 ${summary.roster_count || 0}명</span>
      <span class="badge badge-success">연결 ${summary.ready_count || 0}명</span>
      <span class="badge">파일 ${summary.file_count || 0}개</span>
      ${summary.missing ? `<span class="badge badge-danger">누락 ${summary.missing}</span>` : ''}
      ${summary.name_mismatch ? `<span class="badge badge-warning">이름 불일치 ${summary.name_mismatch}</span>` : ''}
      ${summary.multiple_files ? `<span class="badge badge-warning">여러 파일 ${summary.multiple_files}</span>` : ''}
      ${summary.unregistered ? `<span class="badge badge-warning">명렬 외 ${summary.unregistered}</span>` : ''}
      ${data.all_ready ? '<strong class="inline-status success">✅ 채점 준비 완료</strong>' : ''}
    `;
  }

  window._scannedMaterials = entries
    .filter(entry => entry.files?.length)
    .map(entry => ({ number: entry.number, name: entry.name || entry.discovered_name, files: entry.files }));

  if (!entries.length) {
    listEl.innerHTML = '<div class="empty-state"><div class="icon">📂</div><p>학생·답안 자료가 없습니다. 위에서 폴더 또는 파일을 선택하세요.</p></div>';
    return;
  }

  let rows = '';
  for (const entry of entries) {
    let fileRows = '';
    for (const file of (entry.files || [])) {
      const index = submissionFilesByIndex.push({ file, entry }) - 1;
      const manualAction = file.manual_link
        ? `<button class="btn btn-secondary btn-sm" onclick="resetSubmissionLink(${index})">자동 연결로 되돌리기</button>`
        : '';
      const rosterOptions = roster.map(student =>
        `<option value="${student.number}" ${student.number === entry.number ? 'selected' : ''}>${student.number}. ${esc(student.name || `학생 ${student.number}`)}</option>`
      ).join('');
      const relinkLabel = entry.status === 'name_mismatch' ? '이 학생으로 확인' : '연결 변경';
      const relink = roster.length
        ? `<select id="submissionTarget-${index}" class="submission-target">${rosterOptions}</select>
           <button class="btn btn-secondary btn-sm" onclick="reassignSubmission(${index})">${relinkLabel}</button>`
        : '';
      fileRows += `
        <div class="submission-file-row">
          <button class="chip" onclick="openSubmissionFile(${index})" title="${escAttr(file.path)}">📄 ${esc(file.name)} (${file.size_mb || 0}MB)</button>
          <div class="submission-file-actions">${relink}${manualAction}
            <button class="btn-icon" onclick="removeSubmissionFile(${index})" title="${escAttr(file.name)} 제거">✕</button>
          </div>
        </div>`;
    }
    if (!fileRows) fileRows = '<span class="inline-status danger">연결된 파일이 없습니다.</span>';
    const checked = entry.files?.length ? '' : 'disabled';
    rows += `
      <tr class="submission-row status-${entry.status}">
        <td><input type="checkbox" class="participant-check" value="${entry.number}" ${checked}></td>
        <td>${entry.number}</td>
        <td><strong>${esc(entry.name || entry.discovered_name || `학생 ${entry.number}`)}</strong>
          ${entry.discovered_name && entry.name && entry.discovered_name !== entry.name ? `<small>파일명: ${esc(entry.discovered_name)}</small>` : ''}
        </td>
        <td><span class="submission-status status-${entry.status}">${esc(entry.status_label)}</span></td>
        <td><div class="submission-file-list">${fileRows}</div></td>
      </tr>`;
  }

  const inferButton = data.roster_source === 'files'
    ? '<div class="info-callout">파일명으로 번호와 이름을 찾았습니다. <button class="btn btn-primary btn-sm" onclick="inferRosterFromFiles()">이 명렬을 저장</button></div>'
    : '';
  listEl.innerHTML = `${inferButton}
    <div class="table-wrap"><table>
      <thead><tr><th style="width:30px"><input type="checkbox" id="checkAllMaterials" onclick="toggleAllMaterials(this.checked)"></th><th>번호</th><th>명렬 이름</th><th>상태</th><th>연결 파일</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

async function inferRosterFromFiles() {
  if (!currentSubmissionStatus) return;
  const inferred = (currentSubmissionStatus.entries || [])
    .filter(entry => entry.files?.length)
    .map(entry => ({ number: entry.number, name: entry.name || entry.discovered_name || `학생 ${entry.number}` }));
  if (!inferred.length) return alert('파일명에서 찾을 수 있는 학생이 없습니다.');
  document.getElementById('rosterInput').value = inferred.map(student => `${student.number}, ${student.name}`).join('\n');
  try {
    await saveRoster({ requireStudents: true });
  } catch (error) {
    alert(error.message);
  }
}

function openSubmissionFile(index) {
  const item = submissionFilesByIndex[index];
  if (item) openFile(item.file.path);
}

async function removeSubmissionFile(index) {
  const item = submissionFilesByIndex[index];
  if (!item) return;
  await removeMaterial(item.file.path, item.file.name);
}

async function reassignSubmission(index) {
  const item = submissionFilesByIndex[index];
  const target = document.getElementById(`submissionTarget-${index}`);
  if (!item || !target) return;
  const res = await fetch(`/api/projects/${currentProject.id}/submissions/link`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_path: item.file.path, student_number: parseInt(target.value) }),
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '연결 변경 실패');
  renderSubmissionStatus(data.status);
}

async function resetSubmissionLink(index) {
  const item = submissionFilesByIndex[index];
  if (!item) return;
  const res = await fetch(`/api/projects/${currentProject.id}/submissions/link`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_path: item.file.path }),
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '자동 연결 복구 실패');
  renderSubmissionStatus(data.status);
}

async function resetSubmissionLinks() {
  if (!currentProject) return;
  if (!confirm('교사가 바꾼 파일 연결을 모두 지우고 파일명 기준 자동 연결로 되돌릴까요?')) return;
  const res = await fetch(`/api/projects/${currentProject.id}/submissions/links/reset`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '수동 연결 초기화 실패');
  renderSubmissionStatus(data.status);
}

function toggleAllMaterials(checked) {
  document.querySelectorAll('.participant-check').forEach(el => el.checked = checked);
}

async function startSelectedGrading() {
  const selected = Array.from(document.querySelectorAll('.participant-check:checked')).map(el => parseInt(el.value));
  if (!selected.length) return alert('채점할 학생 또는 모둠을 선택하세요.');
  showWorkspaceStage('grading');
  await startGrading(selected);
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
function roundStatusLabel(status) {
  return ({
    prepared: '준비됨',
    running: '진행 중',
    interrupted: '비정상 종료 · 이어하기 가능',
    stopped: '중단됨',
    partial: '일부 완료',
    completed_with_errors: '실패 있음',
    completed: '완료',
    legacy: '기존 결과',
  })[status] || status || '상태 확인';
}

function criteriaVersionLabel(round) {
  if (round.criteria_version) {
    return `기준 v${round.criteria_version}${round.criteria_version === round.approved_criteria_version ? ' 승인' : ''}`;
  }
  return round.criteria_status ? `기준 ${round.criteria_status}` : '기준 버전 미저장';
}

function gradingRequestPayload(teamNumbers = null, options = {}) {
  const mode = options.mode || document.getElementById('gradingRunMode')?.value || 'new';
  return {
    start_from: Math.max(1, parseInt(options.start_from ?? document.getElementById('startFrom')?.value) || 1),
    delay: Math.max(0, parseInt(document.getElementById('delay')?.value) || 0),
    repeat_count: Math.max(1, parseInt(options.repeat_count ?? document.getElementById('repeatCount')?.value) || 1),
    new_round: options.new_round ?? (mode === 'new'),
    round_id: options.round_id || null,
    retry_failed: Boolean(options.retry_failed),
    team_numbers: teamNumbers,
  };
}

function formatGradingEstimate(plan) {
  const estimate = plan.estimate || {};
  const minutes = estimate.estimated_minutes_range || [0, 0];
  const cost = estimate.estimated_cost_range_krw;
  const costText = cost
    ? ` · 비용 약 ${cost[0].toLocaleString()}~${cost[1].toLocaleString()}원`
    : ' · 비용은 무료/유료 티어와 실제 토큰 사용량에 따라 달라 별도 표시하지 않음';
  const modeText = plan.mode === 'resume'
    ? `${plan.round_id}회차 이어서`
    : (plan.mode === 'retry_failed' ? `${plan.round_id}회차 실패 재시도` : `${plan.round_id}회차부터 새로`);
  return `${modeText} · 대상 ${plan.target_count}명 · 독립 ${plan.repeat_count}회 · 예상 요청 ${estimate.expected_requests || 0}회 · 약 ${minutes[0]}~${minutes[1]}분${costText}`;
}

async function updateGradingPlanEstimate(teamNumbers = null, options = {}) {
  if (!currentProject) return null;
  const element = document.getElementById('gradingPlanEstimate');
  if (element) element.textContent = '예상 요청 수와 시간을 계산하는 중입니다.';
  try {
    const res = await fetch(`/api/projects/${currentProject.id}/grading-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(gradingRequestPayload(teamNumbers, options)),
    });
    const plan = await res.json();
    if (!res.ok) throw new Error(plan.error || '실행 계획 계산 실패');
    if (element) {
      element.innerHTML = `<strong>${esc(formatGradingEstimate(plan))}</strong><span>${esc(plan.estimate?.estimate_note || '')}</span>`;
      element.classList.toggle('has-error', Boolean(plan.context_error));
      if (plan.context_error) element.innerHTML += `<span class="criteria-error">❌ ${esc(plan.context_error)}</span>`;
    }
    return plan;
  } catch (error) {
    if (element) element.textContent = `예상 계산 실패: ${error.message}`;
    return null;
  }
}

function scheduleGradingPlanEstimate() {
  if (gradingPlanTimer) clearTimeout(gradingPlanTimer);
  gradingPlanTimer = setTimeout(() => updateGradingPlanEstimate(), 250);
}

async function loadGradingRounds() {
  if (!currentProject) return;
  const element = document.getElementById('gradingRoundList');
  if (!element) return;
  const res = await fetch(`/api/projects/${currentProject.id}/rounds`);
  const rounds = await res.json();
  if (!res.ok) {
    element.innerHTML = `<div class="criteria-error">${esc(rounds.error || '회차 기록을 불러오지 못했습니다.')}</div>`;
    return;
  }
  currentGradingRounds = rounds;
  if (!rounds.length) {
    element.innerHTML = '<div class="empty-state"><p>아직 회차가 없습니다. 기본값은 전체 대상 독립 채점 2회입니다.</p></div>';
    return;
  }
  element.innerHTML = [...rounds].reverse().map(round => {
    const failureList = (round.failures || []).map(failure => `
      <div class="round-failure-item">
        <strong>${failure.team_number}번 ${esc(failure.team_name || '')}</strong>
        <span>${esc(failure.message)}</span>
        <span class="failure-action">${esc(failure.action || '')}</span>
      </div>`).join('');
    return `<div class="grading-round-card">
      <div class="grading-round-header">
        <div><strong>${round.id}회차</strong><span class="round-status status-${esc(round.status)}">${roundStatusLabel(round.status)}</span></div>
        <div class="round-actions">
          ${round.can_resume ? `<button class="btn btn-secondary btn-sm" onclick="resumeRound(${round.id})">성공 결과 보존하고 이어서</button>` : ''}
          ${round.can_retry ? `<button class="btn btn-warning btn-sm" onclick="retryFailedRound(${round.id})">실패 ${round.failure_count}명 재시도</button>` : ''}
        </div>
      </div>
      <div class="round-metrics">
        <span>성공 ${round.completed_count}/${round.target_count}</span>
        <span>실패 ${round.failure_count}</span>
        <span>시도 ${round.attempt_count || 0}회</span>
      </div>
      <div class="round-context-line">${round.model ? `${esc(round.provider)} · ${esc(round.model)} · ${criteriaVersionLabel(round)}` : '기존 회차 · 모델과 기준 버전 기록 없음'}</div>
      ${failureList ? `<details class="round-failures" open><summary>실패 원인과 복구 안내</summary>${failureList}</details>` : ''}
    </div>`;
  }).join('');
}

async function resumeRound(roundId) {
  document.getElementById('gradingRunMode').value = 'resume';
  document.getElementById('repeatCount').value = 1;
  await startGrading(null, {
    mode: 'resume',
    new_round: false,
    round_id: roundId,
    repeat_count: 1,
    start_from: 1,
  });
}

async function retryFailedRound(roundId) {
  document.getElementById('gradingRunMode').value = 'resume';
  document.getElementById('repeatCount').value = 1;
  await startGrading(null, {
    mode: 'resume',
    new_round: false,
    round_id: roundId,
    retry_failed: true,
    repeat_count: 1,
    start_from: 1,
  });
}

async function loadRegradeCandidates() {
  if (!currentProject) return;
  const element = document.getElementById('regradeCandidateList');
  const stdThreshold = parseFloat(document.getElementById('candidateStdThreshold').value) || 0;
  const rangeThreshold = parseFloat(document.getElementById('candidateRangeThreshold').value) || 0;
  element.innerHTML = '<div class="empty-state"><p>회차 차이를 분석하는 중입니다.</p></div>';
  const res = await fetch(
    `/api/projects/${currentProject.id}/regrade-candidates?std_threshold=${encodeURIComponent(stdThreshold)}&range_threshold=${encodeURIComponent(rangeThreshold)}`
  );
  const data = await res.json();
  if (!res.ok) {
    element.innerHTML = `<div class="criteria-error">${esc(data.error || '차이 대상 분석 실패')}</div>`;
    return;
  }
  currentRegradeCandidates = data.candidates || [];
  const button = document.getElementById('startCandidateRoundButton');
  button.disabled = !currentRegradeCandidates.length;
  if (!currentRegradeCandidates.length) {
    element.innerHTML = `<div class="empty-state"><p>${esc(data.message || '현재 기준을 넘는 차이 대상이 없습니다.')}</p></div>`;
    return;
  }
  element.innerHTML = `
    <div class="candidate-summary">${data.rounds.join('·')}회차 비교 · ${data.evaluated_count}명 중 ${currentRegradeCandidates.length}명 제안</div>
    ${currentRegradeCandidates.map(candidate => `
      <label class="candidate-item">
        <input type="checkbox" class="regrade-candidate-check" value="${candidate.team_number}" checked>
        <span><strong>${candidate.team_number}번 ${esc(candidate.team_name || '')}</strong>
        <small>점수 ${Object.values(candidate.scores).join(' / ')} · ${esc(candidate.reasons.join(' · '))}</small></span>
      </label>`).join('')}`;
}

async function startCandidateRound() {
  const selected = [...document.querySelectorAll('.regrade-candidate-check:checked')]
    .map(input => parseInt(input.value))
    .filter(Number.isFinite);
  if (!selected.length) return alert('추가 채점할 학생을 선택하세요.');
  document.getElementById('gradingRunMode').value = 'new';
  document.getElementById('repeatCount').value = 1;
  await startGrading(selected, { new_round: true, repeat_count: 1 });
}

async function updateGradingRoundContext(activeRound = null) {
  if (!currentProject) return;
  const element = document.getElementById('gradingRoundContext');
  if (!element) return;
  try {
    const [roundRes, statusRes] = await Promise.all([
      fetch(`/api/projects/${currentProject.id}/rounds`),
      fetch('/api/status'),
    ]);
    const rounds = await roundRes.json();
    const status = await statusRes.json();
    if (status.running && status.project_id === currentProject.id) {
      const round = activeRound || status.current_round || (rounds.at(-1)?.id ?? 1);
      element.textContent = `${round}회차 진행 중 · ${status.completed_count || 0}/${status.total_count || 0}명 완료 · 성공 ${status.success_count || 0}명 · 실패 ${status.fail_count || 0}명`;
      return;
    }
    if (!rounds.length) {
      element.textContent = '아직 채점 회차가 없습니다. 기본 실행은 같은 조건으로 독립 채점 2회입니다.';
      return;
    }
    const latest = rounds.at(-1);
    const context = latest.model
      ? `${latest.provider} · ${latest.model} · ${criteriaVersionLabel(latest)}`
      : '기존 회차 · 실행 조건 기록 없음';
    element.textContent = `현재 ${rounds.length}개 회차 · 최근 ${latest.id}회차 ${latest.completed_count}/${latest.target_count}명 성공 · ${roundStatusLabel(latest.status)} · ${context}`;
  } catch (error) {
    element.textContent = '회차 정보를 불러오지 못했습니다. 채점 결과는 기존 방식대로 보존됩니다.';
  }
}

async function renderGradingGrid() {
  if (!currentProject) return;
  const el = document.getElementById('gradingTeamGrid');
  if (!el) return;
  el.innerHTML = '<div style="font-size: 0.85rem; color: var(--text2);">참가자 목록을 불러오는 중...</div>';
  try {
    const [matRes, statRes, roundRes] = await Promise.all([
      fetch(`/api/projects/${currentProject.id}/materials`),
      fetch('/api/status'),
      fetch(`/api/projects/${currentProject.id}/rounds`),
    ]);
    const matData = await matRes.json();
    const statData = await statRes.json();
    const rounds = roundRes.ok ? await roundRes.json() : [];
    
    if (!matData.participants?.length) {
      el.innerHTML = '<div style="font-size: 0.85rem; color: var(--text2);">학생·답안 자료가 없습니다.</div>';
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
    const activeRoundId = (
      statData.running && statData.project_id === currentProject.id
        ? statData.current_round
        : rounds.at(-1)?.id
    );
    const activeRound = rounds.find(round => round.id === activeRoundId);
    const failedTeams = new Set(
      (activeRound?.failures || []).map(failure => Number(failure.team_number))
    );
    
    el.innerHTML = matData.participants.map(t => `
      <div class="team-tile ${failedTeams.has(t.number) ? 'error' : (completedTeams.has(t.number) ? 'done' : '')}" id="tile-team-${t.number}">
        <div class="team-num">${t.number}번</div>
        <div class="team-name">${esc(t.name)}</div>
      </div>
    `).join('');
    updateStats();
  } catch (e) {
    el.innerHTML = '';
  }
}

async function startGrading(teamNumbers = null, options = {}) {
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
  const materialResponse = await fetch(`/api/projects/${currentProject.id}/materials`);
  const materialData = await materialResponse.json();
  if (!materialData.participants?.length) {
    return alert('채점할 학생·답안 자료가 없습니다.\n\n학생·답안 단계에서 폴더를 지정하거나 파일을 추가하세요.');
  }
  const body = gradingRequestPayload(teamNumbers, options);
  const planResponse = await fetch(`/api/projects/${currentProject.id}/grading-plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const plan = await planResponse.json();
  if (!planResponse.ok) return alert(plan.error || '채점 실행 계획을 만들지 못했습니다.');
  if (plan.context_error) {
    alert(`${plan.context_error}\n\n실행 방식을 ‘새 독립 회차로 시작’으로 바꾼 뒤 다시 시도하세요.`);
    return;
  }
  if (!plan.can_start) {
    const message = plan.mode === 'resume'
      ? '이 회차의 대상은 모두 성공했습니다. 새 독립 회차를 시작하세요.'
      : (plan.mode === 'retry_failed'
        ? '이 회차에 다시 시도할 실패 학생이 없습니다.'
        : '선택한 채점 대상이 없습니다.');
    alert(message);
    await loadGradingRounds();
    return;
  }
  const context = plan.execution_context || {};
  const confirmMessage = [
    formatGradingEstimate(plan),
    `실행 조건: ${context.provider || '-'} · ${context.model || '-'} · 기준 v${context.criteria_version || '미저장'}`,
    plan.mode === 'new'
      ? '각 회차는 독립 결과로 저장되며 기존 결과를 덮어쓰지 않습니다.'
      : '이미 성공한 학생은 건너뛰고 남은 대상만 실행합니다.',
    '',
    '채점을 시작하시겠습니까?',
  ].join('\n');
  if (!confirm(confirmMessage)) return;

  const res = await fetch(`/api/projects/${currentProject.id}/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || '채점을 시작하지 못했습니다.');
    if (data.requires_new_round) {
      document.getElementById('gradingRunMode').value = 'new';
      await updateGradingPlanEstimate(teamNumbers, { ...options, mode: 'new', new_round: true });
    }
    return;
  }
  document.getElementById('btnStart').disabled = true;
  document.getElementById('btnStop').disabled = false;
  document.getElementById('gradingLog').innerHTML = '';
  const recovery = document.getElementById('gradingRecoveryGuide');
  if (recovery) {
    recovery.style.display = 'none';
    recovery.textContent = '';
  }
  updateGradingRoundContext(data.round);
  renderGradingGrid();
  loadGradingRounds();
  connectSSE();
  return true;
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
        msg = `❌ ${data.name} 실패: ${data.error}${data.action ? ` · ${data.action}` : ''}`; cls = 'error';
        const te = document.getElementById('tile-team-' + data.team);
        if (te) te.className = 'team-tile error';
        const recovery = document.getElementById('gradingRecoveryGuide');
        if (recovery) {
          recovery.style.display = 'block';
          recovery.innerHTML = `<strong>${esc(data.name)} 복구 안내</strong><span>${esc(data.action || '오류 내용을 확인한 뒤 이 회차의 실패 학생만 다시 시도하세요.')}</span>`;
        }
        break;
      case 'finished': msg = `🏁 채점 완료! 성공: ${data.success}, 실패: ${data.fail}`; cls = 'success';
        document.getElementById('btnStart').disabled = false; document.getElementById('btnStop').disabled = true;
        if (eventSource) { eventSource.close(); eventSource = null; }
        updateGradingRoundContext();
        loadGradingRounds();
        loadOverview();
        updateGradingPlanEstimate();
        break;
      case 'stopped': msg = `⏹ ${data.message}`; cls = 'error';
        document.getElementById('btnStart').disabled = false; document.getElementById('btnStop').disabled = true;
        if (eventSource) { eventSource.close(); eventSource = null; }
        updateGradingRoundContext();
        loadGradingRounds();
        loadOverview();
        updateGradingPlanEstimate();
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
    const roundContext = document.getElementById('gradingRoundContext');
    if (roundContext && state.running && state.project_id === currentProject?.id) {
      roundContext.textContent = `${state.current_round || 1}회차 진행 중 · ${state.completed_count || 0}/${state.total_count || 0}명 완료 · 성공 ${state.success_count || 0}명 · 실패 ${state.fail_count || 0}명`;
    }
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

// ═══ 교사 통합 검토·최종 확정 ═══
function reviewScore(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
    : '-';
}

function selectedReviewRounds() {
  return [...document.querySelectorAll('.review-round-cb:checked')]
    .map(input => Number(input.value))
    .filter(Number.isFinite);
}

async function loadReviewDashboard() {
  if (!currentProject) return;
  const roundContainer = document.getElementById('reviewRoundChecks');
  const body = document.getElementById('reviewBody');
  if (!roundContainer || !body) return;
  body.innerHTML = '<tr><td colspan="12" class="review-loading">검토 자료를 계산하는 중입니다.</td></tr>';
  try {
    const roundsResponse = await fetch(`/api/projects/${currentProject.id}/rounds`);
    const rounds = await roundsResponse.json();
    if (!roundsResponse.ok) throw new Error(rounds.error || '회차를 불러오지 못했습니다.');
    const previousSelection = new Set(selectedReviewRounds());
    const resultRounds = rounds.filter(round => round.completed_count > 0);
    roundContainer.innerHTML = resultRounds.map(round => {
      const checked = !previousSelection.size || previousSelection.has(round.id);
      return `<label class="round-check">
        <input type="checkbox" class="review-round-cb" value="${round.id}" ${checked ? 'checked' : ''}>
        ${round.id}회차 <small>${round.completed_count}/${round.target_count}명</small>
      </label>`;
    }).join('') || '<span class="helper-text">결과가 있는 회차가 없습니다.</span>';

    const params = new URLSearchParams({
      rounds: selectedReviewRounds().join(','),
      std_threshold: document.getElementById('reviewStdThreshold')?.value || '1.5',
      range_threshold: document.getElementById('reviewRangeThreshold')?.value || '2',
      manual_diff_threshold: document.getElementById('reviewManualDiffThreshold')?.value || '2',
    });
    const response = await fetch(`/api/projects/${currentProject.id}/review?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '통합 검토 자료를 만들지 못했습니다.');
    currentReviewDashboard = data;
    const summary = data.summary || {};
    document.getElementById('reviewStudentCount').textContent = summary.student_count || 0;
    document.getElementById('reviewAttentionCount').textContent = summary.attention_count || 0;
    document.getElementById('reviewManualCount').textContent = summary.manual_count || 0;
    document.getElementById('reviewApprovedCount').textContent = summary.effective_approved_count ?? summary.approved_count ?? 0;
    const note = document.getElementById('reviewSelectionNote');
    note.textContent = data.selected_round_ids.length
      ? `${data.selected_round_ids.join('·')}회차의 AI 원점수만으로 평균·중앙값·표준편차를 계산합니다. 수동 점수는 평균에 섞지 않고 차이 확인에만 사용합니다.`
      : '결과 회차가 없습니다. 수동 점수만 저장할 수 있으며 AI 종합 제안은 생성되지 않습니다.';
    renderReviewDashboard();
  } catch (error) {
    body.innerHTML = `<tr><td colspan="12" class="criteria-error">${esc(error.message)}</td></tr>`;
  }
}

function renderReviewDashboard() {
  const body = document.getElementById('reviewBody');
  if (!body || !currentReviewDashboard) return;
  const filter = document.getElementById('reviewFilter')?.value || 'all';
  const students = (currentReviewDashboard.students || []).filter(student => {
    const approved = student.decision?.status === 'approved';
    if (filter === 'attention') return student.review_required;
    if (filter === 'pending') return !approved;
    if (filter === 'approved') return approved;
    return true;
  });
  if (!students.length) {
    body.innerHTML = '<tr><td colspan="12" class="review-loading">현재 조건에 해당하는 학생이 없습니다.</td></tr>';
    return;
  }
  body.innerHTML = students.map(student => {
    const approved = student.decision?.status === 'approved';
    const priority = ({
      critical: '<span class="review-priority critical">긴급 확인</span>',
      attention: '<span class="review-priority attention">우선 확인</span>',
      normal: '<span class="review-priority normal">일반</span>',
    })[student.priority] || '';
    const rounds = currentReviewDashboard.selected_round_ids
      .map(round => {
        const raw = reviewScore(student.scores_by_round?.[round]);
        const adjusted = student.adjusted_scores_by_round?.[round];
        return `${round}회 ${raw}${adjusted != null ? ` → 보정 ${reviewScore(adjusted)}` : ''}`;
      })
      .join('<br>');
    const difference = student.ai_manual_difference;
    const differenceClass = difference != null && Math.abs(difference) >= currentReviewDashboard.thresholds.manual_difference
      ? 'review-difference warning'
      : 'review-difference';
    const finalScore = approved ? reviewScore(student.decision.total_score) : '-';
    const status = approved
      ? `<span class="badge badge-success">최종 확정</span>${student.decision_stale ? '<br><span class="badge badge-danger">자료 변경됨</span>' : ''}`
      : '<span class="badge badge-warning">확정 대기</span>';
    const reasonText = (student.review_reasons || []).map(reason => reason.label).join(' · ');
    return `<tr class="review-row priority-${student.priority}">
      <td>${priority}</td>
      <td>${student.team_number}</td>
      <td>${esc(student.team_name || '')}</td>
      <td class="round-score-cell">${rounds || '-'}</td>
      <td><strong>${reviewScore(student.ai_average)}</strong></td>
      <td>${reviewScore(student.std_dev)}</td>
      <td>${reviewScore(student.manual_score)}</td>
      <td class="${differenceClass}">${difference == null ? '-' : `${difference > 0 ? '+' : ''}${reviewScore(difference)}`}</td>
      <td>${reviewScore(student.ai_suggested_score)}</td>
      <td><strong>${finalScore}</strong></td>
      <td>${status}</td>
      <td><button class="btn btn-primary btn-sm" onclick="openReviewDecision(${student.team_number})">검토·확정</button>
      ${reasonText ? `<div class="review-reasons" title="${esc(reasonText)}">${esc(reasonText)}</div>` : ''}</td>
    </tr>`;
  }).join('');
}

function reviewItemInputs(selector) {
  const values = {};
  document.querySelectorAll(selector).forEach(input => {
    if (input.value !== '') values[input.dataset.id] = Number(input.value);
  });
  return values;
}

function updateReviewTotalsFromItems(kind) {
  const selector = kind === 'manual' ? '.review-manual-item' : '.review-final-item';
  const target = document.getElementById(kind === 'manual' ? 'reviewManualTotal' : 'reviewFinalTotal');
  const inputs = [...document.querySelectorAll(selector)].filter(input => input.value !== '');
  if (!target || !inputs.length) return;
  const total = inputs.reduce((sum, input) => sum + (Number(input.value) || 0), 0);
  target.value = Number(total.toFixed(2));
  if (kind === 'final') document.getElementById('reviewDecisionSource').value = 'custom';
}

function renderReviewAudit(student) {
  const element = document.getElementById('reviewDecisionAudit');
  const entries = student.audit_log || [];
  if (!entries.length) {
    element.innerHTML = '<span>아직 교사 변경 이력이 없습니다.</span>';
    return;
  }
  const labels = {
    manual_score_saved: '수동 점수 저장',
    manual_score_imported: '수동 점수 Excel 가져오기',
    final_score_approved: '최종 점수 확정',
    final_score_reopened: '확정 취소·재검토',
  };
  element.innerHTML = `<details><summary>교사 변경 이력 ${entries.length}건</summary>
    ${[...entries].reverse().slice(0, 10).map(entry => `
      <div class="review-audit-entry">
        <strong>${esc(labels[entry.action] || entry.action)}</strong>
        <span>${esc(formatDateTime(entry.timestamp))}</span>
      </div>`).join('')}
  </details>`;
}

function openReviewDecision(teamNumber) {
  if (!currentReviewDashboard) return;
  const student = currentReviewDashboard.students.find(
    value => value.team_number === Number(teamNumber)
  );
  if (!student) return;
  currentReviewStudent = student;
  const decision = student.decision || {};
  const approved = decision.status === 'approved';
  document.getElementById('reviewDecisionTitle').textContent = `${student.team_number}번 ${student.team_name || ''}`;
  document.getElementById('reviewDecisionSummary').innerHTML = `
    <div class="review-summary-strip">
      <span>AI 평균 <strong>${reviewScore(student.ai_average)}</strong></span>
      <span>AI 중앙값 <strong>${reviewScore(student.ai_median)}</strong></span>
      <span>표준편차 <strong>${reviewScore(student.std_dev)}</strong></span>
      <span>수동 <strong>${reviewScore(student.manual_score)}</strong></span>
      <span>AI-수동 <strong>${student.ai_manual_difference == null ? '-' : `${student.ai_manual_difference > 0 ? '+' : ''}${reviewScore(student.ai_manual_difference)}`}</strong></span>
    </div>
    ${(student.review_reasons || []).length
      ? `<div class="review-modal-reasons">${student.review_reasons.map(reason => `<span>${esc(reason.label)}</span>`).join('')}</div>`
      : '<div class="criteria-ok">현재 임계값을 넘는 특별한 확인 사유는 없습니다.</div>'}
    ${student.decision_stale ? '<div class="criteria-error">확정 이후 회차 또는 수동 점수가 바뀌었습니다. 재검토 후 다시 확정하세요.</div>' : ''}`;
  document.getElementById('reviewDecisionItems').innerHTML = (student.items || []).map(item => {
    const roundScores = currentReviewDashboard.selected_round_ids
      .map(round => `${round}회 ${reviewScore(item.scores_by_round?.[round])}`)
      .join('<br>');
    const finalValue = decision.item_scores?.[item.id] ?? item.suggested_score ?? '';
    return `<tr>
      <td><strong>${esc(item.label)}</strong><br><small>${esc(item.name || '')}</small></td>
      <td class="round-score-cell">${roundScores || '-'}</td>
      <td>${reviewScore(item.ai_average)}</td>
      <td>${reviewScore(item.std_dev)}</td>
      <td><input type="number" class="review-score-input review-manual-item" data-id="${esc(item.id)}" min="0" max="${item.max_score}" step="0.1" value="${item.manual_score ?? ''}" onchange="updateReviewTotalsFromItems('manual')"></td>
      <td><input type="number" class="review-score-input review-final-item" data-id="${esc(item.id)}" min="0" max="${item.max_score}" step="0.1" value="${finalValue}" onchange="updateReviewTotalsFromItems('final')"></td>
    </tr>`;
  }).join('') || '<tr><td colspan="6">평가 항목 정보가 없습니다. 총점만 확정할 수 있습니다.</td></tr>';
  document.getElementById('reviewManualTotal').value = student.manual_score ?? '';
  document.getElementById('reviewManualTotal').max = currentReviewDashboard.max_score;
  document.getElementById('reviewFinalTotal').value = decision.total_score ?? student.ai_suggested_score ?? '';
  document.getElementById('reviewFinalTotal').max = currentReviewDashboard.max_score;
  document.getElementById('reviewDecisionSource').value = decision.decision_source || 'ai_suggested';
  document.getElementById('reviewTeacherNote').value = decision.teacher_note || '';
  document.getElementById('reviewReopenButton').style.display = approved ? '' : 'none';
  document.getElementById('reviewApproveButton').textContent = approved ? '다시 승인·확정' : '교사 승인·최종 확정';
  renderReviewAudit(student);
  openModal('reviewDecisionModal');
}

function applyReviewDecisionSource() {
  if (!currentReviewStudent) return;
  const source = document.getElementById('reviewDecisionSource').value;
  if (source === 'ai_suggested') {
    document.getElementById('reviewFinalTotal').value = currentReviewStudent.ai_suggested_score ?? '';
    document.querySelectorAll('.review-final-item').forEach(input => {
      const item = currentReviewStudent.items.find(value => value.id === input.dataset.id);
      input.value = item?.suggested_score ?? '';
    });
  } else if (source === 'manual') {
    if (currentReviewStudent.manual_score == null) {
      alert('먼저 수동 점수를 입력하고 저장하세요.');
      document.getElementById('reviewDecisionSource').value = 'custom';
      return;
    }
    document.getElementById('reviewFinalTotal').value = currentReviewStudent.manual_score;
    document.querySelectorAll('.review-final-item').forEach(input => {
      const item = currentReviewStudent.items.find(value => value.id === input.dataset.id);
      input.value = item?.manual_score ?? '';
    });
  }
}

async function saveReviewManualScore() {
  if (!currentProject || !currentReviewStudent) return;
  const totalValue = document.getElementById('reviewManualTotal').value;
  const response = await fetch(
    `/api/projects/${currentProject.id}/review/${currentReviewStudent.team_number}/manual`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        total_score: totalValue === '' ? null : Number(totalValue),
        item_scores: reviewItemInputs('.review-manual-item'),
      }),
    }
  );
  const data = await response.json();
  if (!response.ok) return alert(data.error || '수동 점수 저장 실패');
  const teamNumber = currentReviewStudent.team_number;
  await loadReviewDashboard();
  openReviewDecision(teamNumber);
}

async function approveReviewDecision() {
  if (!currentProject || !currentReviewStudent) return;
  const totalValue = document.getElementById('reviewFinalTotal').value;
  if (totalValue === '') return alert('최종 확정 총점을 입력하세요.');
  if (!confirm('AI 원점수와 수동 점수는 그대로 보존하고, 현재 값을 교사 최종 점수로 확정할까요?')) return;
  const response = await fetch(
    `/api/projects/${currentProject.id}/review/${currentReviewStudent.team_number}/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        final_total_score: Number(totalValue),
        item_scores: reviewItemInputs('.review-final-item'),
        teacher_note: document.getElementById('reviewTeacherNote').value,
        decision_source: document.getElementById('reviewDecisionSource').value,
        basis_rounds: currentReviewDashboard.selected_round_ids,
      }),
    }
  );
  const data = await response.json();
  if (!response.ok) return alert(data.error || '최종 점수 확정 실패');
  const teamNumber = currentReviewStudent.team_number;
  await loadReviewDashboard();
  await loadOverview();
  openReviewDecision(teamNumber);
}

async function reopenReviewDecision() {
  if (!currentProject || !currentReviewStudent) return;
  const reason = prompt('확정을 취소하고 재검토하는 이유를 입력하세요. (선택)', '');
  if (reason === null) return;
  const response = await fetch(
    `/api/projects/${currentProject.id}/review/${currentReviewStudent.team_number}/reopen`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }
  );
  const data = await response.json();
  if (!response.ok) return alert(data.error || '재검토 전환 실패');
  const teamNumber = currentReviewStudent.team_number;
  await loadReviewDashboard();
  await loadOverview();
  openReviewDecision(teamNumber);
}

// ═══ 개별 회차 결과 조회 ═══
async function loadRounds(selectId, cb) {
  if (!currentProject) return;
  const res = await fetch(`/api/projects/${currentProject.id}/rounds`);
  const rounds = await res.json();
  const sel = document.getElementById(selectId);
  sel.innerHTML = rounds.map(r => {
    const context = r.model ? ` · ${r.model}` : '';
    return `<option value="${r.id}">${r.id}회차 (${r.completed_count}/${r.target_count}명 · ${roundStatusLabel(r.status)}${esc(context)})</option>`;
  }).join('');
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
      ? '<span class="badge badge-success">회차 확인</span>'
      : `<span class="badge badge-warning">회차 미확인${r.review_required_count ? ` ${r.review_required_count}건` : ''}</span>`;
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
  showWorkspaceStage('grading');
  document.getElementById('gradingRunMode').value = 'new';
  document.getElementById('repeatCount').value = 1;
  await startGrading([teamNum], { mode: 'new', new_round: true, repeat_count: 1 });
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

function getScoredExamQuestions() {
  const questions = currentProject?.exam?.questions || [];
  const parentIds = new Set(questions.filter(question => question.parent_id).map(question => question.parent_id));
  const indexed = questions.map((question, index) => ({ question, index }));
  const ordered = [];
  for (const item of indexed.filter(item => !item.question.parent_id)) {
    ordered.push(item.question);
    ordered.push(...indexed
      .filter(child => child.question.parent_id === item.question.id)
      .sort((a, b) => (a.question.sub_index || 0) - (b.question.sub_index || 0))
      .map(child => child.question));
  }
  return ordered.filter(question => !parentIds.has(question.id));
}

function renderDetail(isEdit = false) {
  const data = currentDetailData;
  const teamNum = data.team_number;
  const round = currentDetailRound;
  
  let titleHtml = `[${teamNum}번] ${esc(data.team_name || '')}`;
  const isExam = currentProject?.project_type === 'exam';
  const approveButton = isExam && data.teacher_status !== 'approved'
    ? `<button class="btn btn-success btn-sm" onclick="approveExamResult(${teamNum}, ${round})">✅ 이 회차 확인 완료</button>` : '';
  const headerAction = isEdit 
    ? `<button class="btn btn-success btn-sm" onclick="saveManualEdit(${teamNum}, ${round})">💾 저장</button>
       <button class="btn btn-secondary btn-sm" onclick="renderDetail(false)">취소</button>`
    : `<button class="btn btn-primary btn-sm" onclick="renderDetail(true)">✏️ 회차 판정 보정</button>${approveButton}`;
  
  document.getElementById('detailTitle').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;width:100%;padding-right:30px">
    <span>${titleHtml}</span>
    <div style="display:flex;gap:8px">${headerAction}</div>
  </div>`;

  let html = isExam
    ? '<table><thead><tr><th>문항</th><th>답안 요약</th><th>점수</th><th>채점 근거</th><th>검토</th></tr></thead><tbody>'
    : '<table><thead><tr><th>영역</th><th>항목</th><th>점수</th><th>채점 근거</th></tr></thead><tbody>';

  if (isExam) {
    for (const q of getScoredExamQuestions()) {
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
    const statusLabel = data.teacher_status === 'approved' ? `✅ 이 회차 교사 확인 완료 (${esc(data.teacher_approved_at || '')})` : '⚠️ 회차 확인 전 AI 점수';
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
    loadReviewDashboard();
  } else {
    alert('저장 실패: ' + result.error);
  }
}

async function approveExamResult(teamNum, round) {
  const note = prompt('이 회차 확인 메모가 있으면 입력하세요. (선택)', currentDetailData.teacher_note || '');
  if (note === null) return;
  if (!confirm('현재 회차의 판정을 확인 완료로 표시할까요?\n최종 점수 확정은 통합 검토 화면에서 별도로 진행합니다.')) return;
  const res = await fetch(`/api/projects/${currentProject.id}/result/${teamNum}/approve?round=${round}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ teacher_note: note })
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || '승인 실패');
  currentDetailData = data.data;
  renderDetail(false);
  loadResults();
  loadReviewDashboard();
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
      loadReviewDashboard();
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

  const query = `rounds=${encodeURIComponent(rounds)}&include_manual=${includeManual}`;
  try {
    const [resultResponse, summaryResponse] = await Promise.all([
      fetch(`/api/projects/${currentProject.id}/analysis?${query}`),
      fetch(`/api/projects/${currentProject.id}/analysis/summary?${query}`),
    ]);
    const results = await resultResponse.json();
    const summary = await summaryResponse.json();
    if (!resultResponse.ok) throw new Error(results.error || '분석 결과를 만들지 못했습니다.');
    if (!summaryResponse.ok) throw new Error(summary.error || '문항별 분석을 만들지 못했습니다.');

    document.getElementById('analysisSummaryCards').style.display = 'grid';
    document.getElementById('analysisStudentCount').textContent = summary.student_count || 0;
    document.getElementById('analysisRoundCount').textContent = summary.round_count || 0;
    document.getElementById('analysisManualMae').textContent = summary.manual_mae == null
      ? '측정 불가'
      : reviewScore(summary.manual_mae);
    document.getElementById('analysisApprovedCount').textContent = summary.approved_count || 0;
    document.getElementById('analysisAttentionCount').textContent = summary.attention_count || 0;

    if (!results.length) {
      document.getElementById('analysisHead').innerHTML = '<th>분석 결과</th>';
      document.getElementById('analysisBody').innerHTML = '<tr><td style="text-align:center;color:var(--text2)">데이터 없음</td></tr>';
    } else {
      const roundIds = [...new Set(results.flatMap(r => Object.keys(r.scores_by_round || {})))];
      let headHtml = '<th>순위</th><th>번호</th><th>이름</th>';
      roundIds.forEach(rid => headHtml += `<th>${esc(rid)}</th>`);
      headHtml += '<th>수동</th><th>AI 평균</th><th>절사평균</th><th>편차</th><th>AI-수동</th><th>AI 제안</th><th>최종 확정</th><th>상태</th><th>검토 사유</th>';
      document.getElementById('analysisHead').innerHTML = headHtml;

      document.getElementById('analysisBody').innerHTML = results.map((row, index) => {
        let html = `<tr><td>${index + 1}</td><td>${row.team_number}</td><td>${esc(row.team_name || '')}</td>`;
        roundIds.forEach(roundId => html += `<td>${reviewScore(row.scores_by_round?.[roundId])}</td>`);
        const difference = row.ai_manual_difference;
        const reasons = (row.review_reasons || []).map(reason => reason.label).join(' · ');
        const status = row.final_status === 'approved'
          ? `<span class="badge badge-success">최종 확정</span>${row.decision_stale ? '<br><span class="badge badge-danger">자료 변경</span>' : ''}`
          : '<span class="badge badge-warning">확정 대기</span>';
        html += `<td>${reviewScore(row.manual_score)}</td><td><strong>${reviewScore(row.average)}</strong></td>`;
        html += `<td>${row.is_trimmed ? reviewScore(row.trimmed_average) : '-'}</td>`;
        html += `<td>${reviewScore(row.std_dev)}</td>`;
        html += `<td>${difference == null ? '-' : `${difference > 0 ? '+' : ''}${reviewScore(difference)}`}</td>`;
        html += `<td>${reviewScore(row.ai_suggested_score)}</td><td><strong>${reviewScore(row.final_score)}</strong></td>`;
        html += `<td>${status}</td><td title="${esc(reasons)}">${esc(reasons || '-')}</td></tr>`;
        return html;
      }).join('');
    }

    const itemSection = document.getElementById('analysisItemSection');
    itemSection.style.display = summary.items?.length ? 'block' : 'none';
    document.getElementById('analysisItemBody').innerHTML = (summary.items || []).map(item => `
      <tr>
        <td>${esc(item.label || '')}</td><td>${reviewScore(item.max_score)}</td>
        <td>${item.student_count}</td><td>${reviewScore(item.ai_average)}</td>
        <td>${reviewScore(item.average_std_dev)}</td><td>${item.manual_count}</td>
        <td>${item.manual_mae == null ? '측정 불가' : reviewScore(item.manual_mae)}</td>
        <td>${item.final_count}</td><td>${item.final_mae == null ? '측정 불가' : reviewScore(item.final_mae)}</td>
      </tr>`).join('');
  } catch (error) {
    document.getElementById('analysisHead').innerHTML = '<th>분석 오류</th>';
    document.getElementById('analysisBody').innerHTML = `<tr><td class="criteria-error">${esc(error.message)}</td></tr>`;
  }
}

async function downloadAnalysisExcel() {
  if (!currentProject) return;
  const checks = document.querySelectorAll('.analysis-round-cb:checked');
  const rounds = Array.from(checks).map(c => c.value).join(',');
  const includeManual = document.getElementById('includeManual').checked;
  window.location.href = `/api/projects/${currentProject.id}/analysis/excel?rounds=${rounds}&include_manual=${includeManual}`;
}

async function loadFeedbackExportPreview() {
  if (!currentProject) return;
  const preview = document.getElementById('feedbackExportPreview');
  if (!preview) return;
  preview.textContent = '내보낼 범위를 확인하는 중입니다.';
  try {
    const response = await fetch(`/api/projects/${currentProject.id}/feedback-export/preview`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '내보낼 범위를 확인하지 못했습니다.');
    preview.innerHTML = [
      `<strong>가상 학생 ${data.student_count}명 · 채점 ${data.round_count}회차 · 성능 레코드 ${data.record_count}건</strong>`,
      `수동 비교 ${esc(data.manual_measurement)} · 최종 확정 비교 ${esc(data.final_measurement)}`,
      `자료 ${data.material_count}개는 형식·크기만 기록하고 원본 ${data.excluded_original_count}개는 모두 제외합니다.`,
      '실제↔가상 학생 대응표는 ZIP에 넣지 않고 이 프로젝트의 private/feedback_mappings에만 저장합니다.',
    ].join('<br>');
  } catch (error) {
    preview.innerHTML = `<span class="criteria-error">${esc(error.message)}</span>`;
  }
}

async function downloadFeedbackExport() {
  if (!currentProject) return;
  const confirmed = confirm(
    '익명 개발 피드백 ZIP을 만들까요?\n\n' +
    '학생 답안·문제지·정답지·루브릭 원본은 포함하지 않습니다.\n' +
    '실제 학생 대응표는 이 컴퓨터의 프로젝트 private 폴더에만 저장됩니다.'
  );
  if (!confirmed) return;
  const button = document.getElementById('feedbackExportButton');
  const status = document.getElementById('feedbackExportStatus');
  button.disabled = true;
  status.className = 'inline-status';
  status.textContent = '익명화·개인정보 검사를 진행하는 중입니다.';
  try {
    const response = await fetch(`/api/projects/${currentProject.id}/feedback-export`, {
      method: 'POST',
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || '피드백 묶음을 만들지 못했습니다.');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plainName = disposition.match(/filename="?([^";]+)"?/i);
    const filename = utf8Name
      ? decodeURIComponent(utf8Name[1])
      : (plainName?.[1] || '개발용_성능자료.zip');
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
    const exportId = response.headers.get('X-AI-Grader-Export-ID') || '';
    status.className = 'inline-status success';
    status.textContent = `완료${exportId ? ` · ${exportId}` : ''} · 로컬 대응표 별도 저장`;
  } catch (error) {
    status.className = 'inline-status danger';
    status.textContent = `실패: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

// ═══ 대회 순위 조정 ═══
let previewResults = null;
let competitionState = null;
let dragIdx = null;

function competitionAllowedScores() {
  return (document.getElementById('competitionAllowedScores')?.value || '')
    .split(',')
    .map(value => Number(value.trim()))
    .filter(Number.isFinite);
}

function competitionTeamsPayload() {
  return submissionData.map(item => ({
    team_number: item.team_number,
    tie_with_previous: Boolean(item.tie_with_previous),
    override_score: item.override_score === '' ? null : item.override_score,
    exception_reason: item.exception_reason || '',
  }));
}

async function loadCompetitionState() {
  if (!currentProject || currentProject.workflow_type !== 'competition') return;
  const response = await fetch(`/api/projects/${currentProject.id}/competition-ranking`);
  const data = await response.json();
  const status = document.getElementById('competitionSavedStatus');
  if (!response.ok) {
    status.textContent = data.error || '순위 조정 이력을 불러오지 못했습니다.';
    return;
  }
  competitionState = data;
  const allowedInput = document.getElementById('competitionAllowedScores');
  if (allowedInput && !allowedInput.value) {
    allowedInput.value = (data.current?.allowed_scores || data.default_allowed_scores || []).join(', ');
  }
  if (data.current) {
    status.innerHTML = `<strong>확정 v${data.current.version} · ${data.current.source_round}회차 기준</strong>` +
      ` · ${data.current.summary.team_count}팀 · 점수 변경 ${data.current.summary.changed_score_count}팀` +
      `${data.current_stale ? '<br><span class="criteria-error">원 평가 결과가 확정 뒤 변경되어 다시 확정해야 합니다.</span>' : ''}`;
  } else {
    status.textContent = '아직 교사가 확정한 순위 조정안이 없습니다.';
  }
  document.getElementById('btnExportExcel').disabled = !data.current || data.current_stale;
  renderCompetitionHistory(data.history || []);
}

function renderCompetitionHistory(history) {
  const container = document.getElementById('competitionHistory');
  if (!container) return;
  if (!history.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = `<h3>확정 변경 이력</h3>
    <div class="competition-history-list">${[...history].reverse().map(item => `
      <div>
        <strong>v${item.version}</strong>
        <span>${item.source_round}회차 · ${formatDateTime(item.approved_at)}</span>
        <small>공동순위 ${item.summary?.tie_team_count || 0}팀 · 수동 예외 ${item.summary?.manual_exception_count || 0}팀 · 점수 변경 ${item.summary?.changed_score_count || 0}팀</small>
        ${item.approval_note ? `<p>${esc(item.approval_note)}</p>` : ''}
      </div>`).join('')}</div>`;
}

async function loadSubmission() {
  if (!currentProject) return;
  const round = Number(document.getElementById('subRound').value);
  if (!round) return;
  const response = await fetch(`/api/projects/${currentProject.id}/results?round=${round}`);
  const results = await response.json();
  if (!response.ok || !Array.isArray(results)) {
    alert(results.error || '원 평가 결과를 불러오지 못했습니다.');
    return;
  }
  submissionData = results.map(result => ({
    team_number: result.team_number,
    team_name: result.team_name,
    evaluation_score: result.total_score,
    tie_with_previous: false,
    override_score: null,
    exception_reason: '',
  }));
  previewResults = null;
  document.getElementById('btnApproveCompetition').disabled = true;
  document.getElementById('submissionPreview').innerHTML = '';
  renderSubmission();
}

function competitionDisplayRanks() {
  let rank = 1;
  let groupStart = 0;
  return submissionData.map((item, index) => {
    if (index === 0 || !item.tie_with_previous) {
      rank = index + 1;
      groupStart = index;
    }
    return { rank, groupStart };
  });
}

function renderSubmission() {
  const tbody = document.getElementById('submissionBody');
  const ranks = competitionDisplayRanks();
  tbody.innerHTML = submissionData.map((item, index) => `
    <tr draggable="true" ondragstart="dragStart(event,${index})" ondragover="dragOver(event)" ondrop="drop(event,${index})">
      <td class="drag-handle">☰</td>
      <td>${ranks[index].rank}위</td>
      <td><label class="tie-check"><input type="checkbox" ${item.tie_with_previous ? 'checked' : ''} ${index === 0 ? 'disabled' : ''} onchange="setCompetitionTie(${index},this.checked)"> 위와 공동</label></td>
      <td>${item.team_number}</td>
      <td>${esc(item.team_name || '')}</td>
      <td><strong>${reviewScore(item.evaluation_score)}</strong></td>
      <td><input class="competition-score-input" type="number" min="0" step="0.1" value="${item.override_score ?? ''}" placeholder="자동" onchange="setCompetitionField(${index},'override_score',this.value)"></td>
      <td><input class="competition-reason-input" value="${escAttr(item.exception_reason || '')}" placeholder="직접 변경 시 필수" oninput="setCompetitionField(${index},'exception_reason',this.value)"></td>
    </tr>`).join('');
}

function setCompetitionTie(index, checked) {
  submissionData[index].tie_with_previous = index > 0 && checked;
  previewResults = null;
  document.getElementById('btnApproveCompetition').disabled = true;
  document.getElementById('submissionPreview').innerHTML = '';
  renderSubmission();
}

function setCompetitionField(index, field, value) {
  submissionData[index][field] = field === 'override_score'
    ? (value === '' ? null : Number(value))
    : value;
  previewResults = null;
  document.getElementById('btnApproveCompetition').disabled = true;
}

function dragStart(event, index) {
  dragIdx = index;
  event.dataTransfer.effectAllowed = 'move';
}
function dragOver(event) { event.preventDefault(); }
function drop(event, index) {
  event.preventDefault();
  if (dragIdx === null || dragIdx === index) return;
  const [item] = submissionData.splice(dragIdx, 1);
  item.tie_with_previous = false;
  submissionData.splice(index, 0, item);
  submissionData[0].tie_with_previous = false;
  dragIdx = null;
  previewResults = null;
  document.getElementById('btnApproveCompetition').disabled = true;
  document.getElementById('submissionPreview').innerHTML = '';
  renderSubmission();
}

function renderCompetitionPreview(plan, title = '자동 배정 미리보기') {
  const preview = document.getElementById('submissionPreview');
  const summary = plan.summary || {};
  preview.innerHTML = `<h3>${esc(title)}</h3>
    <div class="review-summary-strip">
      <span>팀 <strong>${summary.team_count || 0}</strong></span>
      <span>순위 그룹 <strong>${summary.rank_group_count || 0}</strong></span>
      <span>공동순위 팀 <strong>${summary.tie_team_count || 0}</strong></span>
      <span>수동 예외 <strong>${summary.manual_exception_count || 0}</strong></span>
      <span>원점수와 달라짐 <strong>${summary.changed_score_count || 0}</strong></span>
    </div>
    <div class="table-wrap"><table><thead><tr>
      <th>최종 순위</th><th>공동</th><th>번호</th><th>이름</th>
      <th>원 평가점수</th><th>자동 배정</th><th>최종 배정</th><th>변화</th><th>예외 사유</th>
    </tr></thead><tbody>${(plan.entries || []).map(entry => `
      <tr>
        <td><strong>${entry.rank}위</strong></td><td>${entry.tie ? '공동' : ''}</td>
        <td>${entry.team_number}</td><td>${esc(entry.team_name || '')}</td>
        <td>${reviewScore(entry.evaluation_score)}</td><td>${reviewScore(entry.auto_final_score)}</td>
        <td><strong>${reviewScore(entry.final_score)}</strong></td>
        <td>${entry.score_change == null ? '-' : `${entry.score_change > 0 ? '+' : ''}${reviewScore(entry.score_change)}`}</td>
        <td>${esc(entry.exception_reason || '')}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

async function previewSubmission() {
  if (!currentProject || !submissionData.length) return alert('먼저 원 평가 결과를 불러오세요.');
  const sourceRound = Number(document.getElementById('subRound').value);
  const allowedScores = competitionAllowedScores();
  if (!allowedScores.length) return alert('허용 최종 점수를 쉼표로 구분해 입력하세요.');
  const preview = document.getElementById('submissionPreview');
  preview.innerHTML = '<div class="review-loading">순위와 최종 점수를 계산하는 중입니다.</div>';
  try {
    const response = await fetch(`/api/projects/${currentProject.id}/competition-ranking/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_round: sourceRound,
        teams: competitionTeamsPayload(),
        allowed_scores: allowedScores,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '순위 미리보기를 만들지 못했습니다.');
    previewResults = data;
    renderCompetitionPreview(data);
    document.getElementById('btnApproveCompetition').disabled = false;
  } catch (error) {
    preview.innerHTML = `<div class="criteria-error">${esc(error.message)}</div>`;
  }
}

async function approveCompetitionRanking() {
  if (!previewResults) return alert('먼저 자동 배정 미리보기를 확인하세요.');
  if (!confirm('현재 순위와 최종 배정점수를 교사 확정안으로 저장할까요?\\n원 평가점수는 변경되지 않습니다.')) return;
  const response = await fetch(`/api/projects/${currentProject.id}/competition-ranking/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_round: Number(document.getElementById('subRound').value),
      teams: competitionTeamsPayload(),
      allowed_scores: competitionAllowedScores(),
      approval_note: document.getElementById('competitionApprovalNote').value,
    }),
  });
  const data = await response.json();
  if (!response.ok) return alert(data.error || '순위 확정에 실패했습니다.');
  previewResults = data.current;
  renderCompetitionPreview(data.current, `교사 확정 v${data.current.version}`);
  document.getElementById('btnApproveCompetition').disabled = true;
  await loadCompetitionState();
}

async function loadSavedCompetitionRanking() {
  await loadCompetitionState();
  const current = competitionState?.current;
  if (!current) return alert('저장된 확정안이 없습니다.');
  document.getElementById('subRound').value = String(current.source_round);
  document.getElementById('competitionAllowedScores').value = current.allowed_scores.join(', ');
  document.getElementById('competitionApprovalNote').value = current.approval_note || '';
  submissionData = current.entries.map((entry, index, entries) => ({
    team_number: entry.team_number,
    team_name: entry.team_name,
    evaluation_score: entry.evaluation_score,
    tie_with_previous: index > 0 && entry.rank === entries[index - 1].rank,
    override_score: entry.manual_exception ? entry.final_score : null,
    exception_reason: entry.exception_reason || '',
  }));
  previewResults = current;
  renderSubmission();
  renderCompetitionPreview(current, `저장된 교사 확정 v${current.version}`);
  document.getElementById('btnApproveCompetition').disabled = true;
}

async function exportSubmissionExcel() {
  if (!currentProject || !competitionState?.current || competitionState.current_stale) {
    return alert('변경되지 않은 교사 확정안이 있어야 Excel을 만들 수 있습니다.');
  }
  const response = await fetch(`/api/projects/${currentProject.id}/competition-ranking/excel`);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    return alert(data.error || '확정 순위표 Excel 생성에 실패했습니다.');
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '대회_최종순위표.xlsx';
  anchor.click();
  URL.revokeObjectURL(url);
}

// ═══ 첫 실행·화면별 도움말 ═══
const HELP_BY_TAB = {
  projects: {
    title: '프로젝트 시작',
    description: '가장 가까운 평가 유형을 선택해 새 프로젝트를 만듭니다.',
    steps: ['처음이면 가상 샘플로 전체 흐름을 먼저 확인합니다.', '보고서·대회·정기고사 서술형 중 하나를 선택합니다.', '프로젝트를 만든 뒤 개요의 다음 작업 버튼을 따릅니다.'],
  },
  overview: {
    title: '개요와 다음 작업',
    description: '준비 상태, 독립 채점 회차와 교사 확정 진행률을 확인합니다.',
    steps: ['상단 진행률과 다음 할 일을 확인합니다.', '준비 카드에서 문제가 있는 단계로 바로 이동합니다.', '전체 대상 독립 채점 2회와 교사 확정 완료 여부를 확인합니다.'],
  },
  settings: {
    title: '보고서·대회 평가기준',
    description: '공식 루브릭을 반영하거나 자동 초안을 만든 뒤 교사가 승인합니다.',
    steps: ['공식 기준 파일 또는 간단한 평가 설명을 입력합니다.', '항목·척도·상세 기준과 AI용 핵심 기준을 검토합니다.', '저장 버전을 만든 뒤 교사 승인합니다.'],
  },
  exam: {
    title: '서술형 문항과 채점기준',
    description: '문제·정답·기준을 대문항과 소문항 구조로 정리합니다.',
    steps: ['문제지와 기준표가 있으면 함께 올립니다.', '소문항 배점 합과 모범답안·부분점 요소를 확인합니다.', 'AI 전달 수준을 선택하고 기준 버전을 승인합니다.'],
  },
  materials: {
    title: '학생·답안 준비',
    description: '명렬, 통합 스캔 분할과 학생별 파일 연결을 한 화면에서 처리합니다.',
    steps: ['실제 스캔 순서대로 명렬을 저장합니다.', '통합 PDF는 분할 미리보기에서 쪽 범위를 먼저 확인합니다.', '파일 없음·이름 불일치·여러 파일 상태를 모두 해결합니다.'],
  },
  grading: {
    title: 'AI 독립 채점',
    description: '공급자·모델·기준 버전을 고정한 독립 회차를 실행합니다.',
    steps: ['대상·예상 요청 수·시간·비용을 확인합니다.', '기본 독립 채점 2회를 실행합니다.', '중단되면 성공 결과를 보존한 채 이어하거나 실패 학생만 재시도합니다.'],
  },
  results: {
    title: '교사 검토와 최종 확정',
    description: 'AI 편차와 수동 점수 차이를 보고 교사가 최종 점수를 결정합니다.',
    steps: ['우선 확인·확정 대기 필터로 검토 순서를 정합니다.', '회차별 AI와 항목별 근거를 확인합니다.', 'AI 제안·수동 점수·직접 결정 중 근거를 골라 최종 확정합니다.'],
  },
  analysis: {
    title: '확정 점수와 분석 내보내기',
    description: '확정 점수표, 문항별 신뢰도와 익명 개발 피드백 자료를 만듭니다.',
    steps: ['회차와 수동 점수 포함 여부를 선택해 분석합니다.', '첫 시트가 확정 점수표인 Excel을 저장합니다.', '대회는 순위 조정안을 확정하고, 개발 피드백은 원본 제외 범위를 확인합니다.'],
  },
};

function activeHelpTab() {
  const active = document.querySelector('.tab-content.active');
  return active?.id?.replace('tab-', '') || 'projects';
}

function openHelpModal(autoOpen = false) {
  const help = HELP_BY_TAB[activeHelpTab()] || HELP_BY_TAB.projects;
  document.getElementById('helpCurrentTitle').textContent = help.title;
  document.getElementById('helpCurrentDescription').textContent = help.description;
  document.getElementById('helpCurrentSteps').innerHTML = help.steps
    .map(step => `<li>${esc(step)}</li>`)
    .join('');
  document.getElementById('helpDoNotAutoOpen').checked =
    localStorage.getItem('aiGraderGuideSeen') === '1';
  if (!autoOpen) document.getElementById('helpDiagnostics').style.display = 'none';
  openModal('helpModal');
}

function closeHelpModal() {
  if (document.getElementById('helpDoNotAutoOpen').checked) {
    localStorage.setItem('aiGraderGuideSeen', '1');
  } else {
    localStorage.removeItem('aiGraderGuideSeen');
  }
  closeModal('helpModal');
}

async function createSampleProjectFromHelp() {
  if (!confirm('실제 학생 정보와 AI 호출이 없는 가상 샘플 프로젝트를 만들까요?')) return;
  const button = document.getElementById('sampleProjectButton');
  const status = document.getElementById('sampleProjectStatus');
  button.disabled = true;
  status.textContent = '가상 자료와 결과를 만드는 중입니다.';
  try {
    const response = await fetch('/api/sample-project', { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '샘플을 만들지 못했습니다.');
    status.className = 'inline-status success';
    status.textContent = data.message;
    await loadProjects();
    await selectProject(data.project.id, true);
    closeHelpModal();
    showWorkspaceStage('overview');
  } catch (error) {
    status.className = 'inline-status danger';
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function runAppDiagnostics() {
  const container = document.getElementById('helpDiagnostics');
  container.style.display = 'block';
  container.innerHTML = '<div class="review-loading">환경과 프로젝트 상태를 검사하는 중입니다.</div>';
  const query = currentProject ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
  try {
    const response = await fetch(`/api/diagnostics${query}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '진단을 실행하지 못했습니다.');
    const project = data.project;
    const issues = data.issues || [];
    const dependencyFailures = (data.dependencies || []).filter(item => item.required && !item.available);
    container.innerHTML = `
      <div class="diagnostic-summary">
        <span>앱 <strong>${esc(data.app_version)}</strong></span>
        <span>프로젝트 저장 <strong>${data.projects_writable ? '정상' : '확인 필요'}</strong></span>
        <span>필수 구성요소 <strong>${dependencyFailures.length ? `${dependencyFailures.length}개 누락` : '정상'}</strong></span>
        <span>OpenAI 키 <strong>${data.api_keys?.openai ? '설정됨' : '미설정'}</strong></span>
        <span>Gemini 키 <strong>${data.api_keys?.google ? '설정됨' : '미설정'}</strong></span>
        ${project ? `<span>전체 채점 <strong>${project.full_round_count}/2회</strong></span><span>최종 확정 <strong>${project.approved_count}/${project.participant_count}</strong></span>` : ''}
      </div>
      <div class="diagnostic-issues">${issues.length ? issues.map(issue => `
        <div class="diagnostic-issue ${esc(issue.severity)}">
          <strong>${esc(issue.message)}</strong>
          <small>${esc(issue.action)}</small>
        </div>`).join('') : '<div class="diagnostic-issue"><strong>치명적인 환경 문제가 발견되지 않았습니다.</strong></div>'}</div>`;
  } catch (error) {
    container.innerHTML = `<div class="criteria-error">${esc(error.message)}</div>`;
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
function escAttr(s) { return esc(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function formatDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

// ═══ 초기화 ═══
document.addEventListener('DOMContentLoaded', async () => {
  await loadProviders();
  await loadModels();
  await populateWizardProviders();
  renderWizardMaterialOptions();
  await loadProjects();
  const lastId = localStorage.getItem('lastProjectId');
  if (lastId && !currentProject) {
    try {
      await selectProject(lastId, true);
      showWorkspaceStage('overview');
    } catch(e) {
      localStorage.removeItem('lastProjectId');
      currentProject = null;
      updateAppShell();
      showTab('projects');
    }
  }
  ['startFrom', 'delay', 'repeatCount', 'gradingRunMode'].forEach(id => {
    const input = document.getElementById(id);
    if (input) input.addEventListener('change', scheduleGradingPlanEstimate);
  });
  setInterval(updateStats, 3000);
  if (localStorage.getItem('aiGraderGuideSeen') !== '1') {
    setTimeout(() => openHelpModal(true), 250);
  }
});

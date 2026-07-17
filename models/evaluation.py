"""
동적 Pydantic 평가 모델 생성
- 프로젝트 rubric 설정에서 런타임에 Pydantic 모델을 자동 생성
"""
from pydantic import BaseModel, Field, create_model
from typing import Any
from models.project import ProjectConfig, Criterion


def build_evaluation_model(config: ProjectConfig) -> type[BaseModel]:
    """프로젝트 설정에서 동적 Pydantic 모델 생성"""
    
    fields: dict[str, Any] = {
        "team_number": (int, Field(description="참가자/팀 번호")),
        "team_name": (str, Field(description="참가자/팀 이름")),
    }
    
    if config.project_type == "exam":
        for question in config.exam.questions:
            # 점수보다 먼저 답의 존재 여부를 판정하게 해 환각 부분점수를 차단한다.
            fields[f"{question.id}_has_answer"] = (
                bool,
                Field(
                    description=(
                        f"{question.number}번 답이 답안지에 실제로 존재하면 true, "
                        "답란이 비었거나 그 문항의 답을 찾을 수 없으면 false"
                    ),
                ),
            )
            fields[question.id] = (
                int,
                Field(
                    description=f"{question.number}번 점수 (0~{question.max_score})",
                    ge=0,
                    le=question.max_score,
                ),
            )
            fields[f"{question.id}_answer_summary"] = (
                str,
                Field(description=f"{question.number}번 학생 답안의 핵심 내용 요약"),
            )
            fields[f"{question.id}_reason"] = (
                str,
                Field(description=f"{question.number}번 점수의 구체적인 채점 근거"),
            )
            fields[f"{question.id}_confidence"] = (
                float,
                Field(description="채점 확신도 0~1", ge=0.0, le=1.0),
            )
            fields[f"{question.id}_review_required"] = (
                bool,
                Field(description="판독 불가·대안 답안 등 교사 확인이 필요하면 true"),
            )
    else:
        for criterion in config.all_criteria:
        # 점수 필드
            fields[criterion.id] = (
                int,
                Field(
                    description=f"{criterion.description} ({'/'.join(str(s) for s in criterion.scale)})",
                    ge=criterion.min_score,
                    le=criterion.max_score,
                ),
            )
            # 근거 필드
            fields[f"{criterion.id}_reason"] = (
                str,
                Field(description=f"{criterion.name} 채점 근거 (한국어, 2~3문장)"),
            )
    
    # 종합 의견
    fields["overall_comment"] = (
        str,
        Field(description="종합 평가 의견 (한국어, 3~5문장으로 강점과 개선점 요약)"),
    )
    
    # 세특(세부능력 및 특기사항) 문구
    if config.project_type != "exam":
        fields["seteuk"] = (
            str,
            Field(description="학교생활기록부 세부능력 및 특기사항 기재용 문구. 3인칭 서술체로 해당 학생의 탐구 활동, 역량, 성장을 구체적으로 기술. 300자 내외."),
        )
    
    # 동적 모델 생성
    EvalModel = create_model("DynamicEvaluation", **fields)
    return EvalModel


def compute_scores(config: ProjectConfig, eval_data: dict) -> dict:
    """채점 결과에 소계 및 합계 계산 추가"""
    result = dict(eval_data)
    
    if config.project_type == "exam":
        # 답이 없다고 판정된 문항은 모델이 점수를 주었더라도 0점으로 강제한다.
        # 프롬프트 지시(부탁)와 달리 코드 수준에서 환각 부분점수를 차단한다.
        for q in config.exam.questions:
            has_key = f"{q.id}_has_answer"
            if has_key in result and not bool(result.get(has_key)):
                original_score = int(result.get(q.id, 0) or 0)
                result[q.id] = 0
                result[f"{q.id}_answer_summary"] = "무응답"
                result[f"{q.id}_review_required"] = True
                note = "답안 없음(무응답)으로 0점 처리."
                if original_score:
                    note += f" AI가 제시했던 {original_score}점은 무효화됨."
                result[f"{q.id}_reason"] = note
        total = sum(int(result.get(q.id, 0) or 0) for q in config.exam.questions)
        result["total_score"] = total
        result["ai_total_score"] = total
        result["review_required_count"] = sum(
            1 for q in config.exam.questions if bool(result.get(f"{q.id}_review_required", False))
        )
        result.setdefault("teacher_status", "pending")
        result.setdefault("teacher_note", "")
        result.setdefault("audit_log", [])
        return result

    total = 0
    for cat in config.categories:
        cat_total = 0
        for criterion in cat.criteria:
            score = eval_data.get(criterion.id, 0)
            cat_total += score
        
        # 카테고리 소계 키: "카테고리명_total" (공백/특문 제거)
        cat_key = cat.name.replace(" ", "_") + "_total"
        result[cat_key] = cat_total
        total += cat_total
    
    result["total_score"] = total
    return result


def generate_fake_subscores_dynamic(config: ProjectConfig, target_total: float) -> dict:
    """
    목표 총점에 맞는 세부항목 점수를 역생성 (제출용 채점표용)
    DP로 유효한 척도 조합을 찾아 모든 세부 점수가 정상 범위 내에 있도록 보장
    """
    import random
    
    criteria = config.all_criteria
    if not criteria:
        return {"total_score": int(round(target_total))}
    
    target = int(round(target_total))
    n = len(criteria)
    
    # ── DP 1단계: 각 항목 이후로 달성 가능한 합계 집합 계산 ──
    # achievable[i] = criteria[i:]를 사용해 만들 수 있는 합계 집합
    achievable = [set() for _ in range(n + 1)]
    achievable[n] = {0}
    
    for i in range(n - 1, -1, -1):
        c = criteria[i]
        for val in c.scale:
            for s in achievable[i + 1]:
                achievable[i].add(val + s)
    
    # ── DP 2단계: 역추적으로 유효한 조합 선택 (랜덤) ──
    scores = {}
    remaining = target
    
    for i in range(n):
        c = criteria[i]
        # 이 값을 선택했을 때, 남은 항목들로 나머지를 달성할 수 있는 옵션만 선택
        options = [val for val in c.scale if (remaining - val) in achievable[i + 1]]
        
        if options:
            chosen = random.choice(options)
        else:
            # target이 유효하지 않은 경우 (발생하면 안 됨) → 가장 가까운 값 선택
            chosen = min(c.scale, key=lambda v: abs(remaining - v))
        
        scores[c.id] = chosen
        remaining -= chosen
    
    # ── 카테고리 소계 및 총점 계산 ──
    result = dict(scores)
    total = 0
    for cat in config.categories:
        cat_total = sum(scores.get(c.id, 0) for c in cat.criteria)
        cat_key = cat.name.replace(" ", "_") + "_total"
        result[cat_key] = cat_total
        total += cat_total
    
    result["total_score"] = total
    return result

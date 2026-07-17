import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from models.project import ProjectConfig

# 사용자의 실제 config.json 로드
config = ProjectConfig.from_dict({
    "categories": [
        {"name": "새 영역", "criteria": [
            {"id": "c1", "name": "항목1", "description": "", "scale": [5,4,3,2,1], "scale_labels": ["a","b","c","d","e"]},
            {"id": "c2", "name": "항목2", "description": "", "scale": [5,4,3,2,1], "scale_labels": ["a","b","c","d","e"]},
            {"id": "c3", "name": "항목3", "description": "", "scale": [5,4,3,2,1], "scale_labels": ["a","b","c","d","e"]},
        ]},
        {"name": "새 영역", "criteria": [
            {"id": "c1", "name": "항목1", "description": "", "scale": [5,4,3,2,1], "scale_labels": ["a","b","c","d","e"]},
        ]},
    ],
    "total_max_score": 20
})

print("=== 중복 보정 결과 ===")
for cat in config.categories:
    print(f"영역: {cat.name}")
    for c in cat.criteria:
        print(f"  - {c.id}: {c.name} (scale: {c.scale})")

print(f"\nall_criteria IDs: {[c.id for c in config.all_criteria]}")
print(f"고유 ID 수: {len(set(c.id for c in config.all_criteria))}")
print(f"전체 항목 수: {len(config.all_criteria)}")

# 점수 생성 테스트
from models.evaluation import generate_fake_subscores_dynamic
result = generate_fake_subscores_dynamic(config, 18)
print(f"\n=== 총점 18 세부 배분 ===")
for c in config.all_criteria:
    print(f"  {c.id}: {result[c.id]}")
for cat in config.categories:
    key = cat.name.replace(" ", "_") + "_total"
    actual = sum(result[c.id] for c in cat.criteria)
    print(f"  {cat.name} 소계: 저장값={result.get(key)} 실제합={actual}")
print(f"  총점: {result['total_score']}")

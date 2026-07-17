"""
파일 관리 서비스
- 폴더 탐색으로 심사자료 자동 발견
- 웹 업로드 처리
"""
import re
from pathlib import Path
from typing import Optional
from models.project import ProjectConfig, resolve_project_path
from config import SUPPORTED_FILE_TYPES, PROJECTS_DIR


def _path_key(value: str | Path) -> str:
    return str(Path(value).resolve(strict=False)).casefold()


def _apply_manual_links(config: ProjectConfig, participants: list[dict]) -> list[dict]:
    """교사가 수정한 파일 연결을 자동 파일명 연결 위에 덧씌운다."""
    if not config.submissions.manual_links:
        return participants

    links = {}
    for link in config.submissions.manual_links:
        resolved = resolve_project_path(
            config.id, link.file_path, expected_subdir="materials"
        )
        links[_path_key(resolved)] = link.student_number

    roster_names = {
        student.number: student.name
        for student in config.roster_students
        if student.name
    }
    rebuilt: dict[int, dict] = {}
    for participant in participants:
        for file_info in participant.get("files", []):
            original_number = participant["number"]
            target_number = links.get(_path_key(file_info["path"]), original_number)
            manually_linked = target_number != original_number or _path_key(file_info["path"]) in links
            if target_number not in rebuilt:
                rebuilt[target_number] = {
                    "number": target_number,
                    "name": (
                        roster_names.get(target_number)
                        if manually_linked
                        else participant.get("name", f"참가자 {target_number}")
                    ) or f"참가자 {target_number}",
                    "files": [],
                }
            copied = dict(file_info)
            copied["manual_link"] = manually_linked
            copied["auto_number"] = original_number
            rebuilt[target_number]["files"].append(copied)

    return sorted(rebuilt.values(), key=lambda item: item["number"])


def find_materials(config: ProjectConfig, *, apply_links: bool = True) -> list[dict]:
    """프로젝트 설정에 따라 심사자료를 탐색하여 참가자 목록 반환
    - 폴더 스캔 결과 + 프로젝트 materials 폴더의 추가 파일을 합침
    - excluded_files에 포함된 파일은 제외
    """
    participants = {}
    excluded = set(config.materials.excluded_files) if config.materials.excluded_files else set()
    
    # 1. 메인 폴더 스캔
    if config.materials.source_type == "folder" and config.materials.folder_path:
        for p in _scan_folder(config):
            participants[p["number"]] = p
    
    # 2. 프로젝트 materials 폴더 (파일 추가로 복사된 파일)
    uploaded = _scan_uploads(config)
    for p in uploaded:
        if p["number"] in participants:
            # 기존 참가자에 파일 병합 (중복 파일명 제거)
            existing_names = {f["name"] for f in participants[p["number"]]["files"]}
            for f in p["files"]:
                if f["name"] not in existing_names:
                    participants[p["number"]]["files"].append(f)
        else:
            participants[p["number"]] = p
    
    # 3. 제외 목록 필터링
    if excluded:
        for num in list(participants.keys()):
            participants[num]["files"] = [
                f for f in participants[num]["files"]
                if f["path"] not in excluded
            ]
            # 파일이 모두 제외된 참가자는 목록에서 제거
            if not participants[num]["files"]:
                del participants[num]
    
    result = sorted(participants.values(), key=lambda x: x["number"])
    return _apply_manual_links(config, result) if apply_links else result


def _scan_folder(config: ProjectConfig) -> list[dict]:
    """지정 폴더에서 파일을 탐색하여 참가자별로 묶음"""
    folder_path = Path(config.materials.folder_path)
    if not folder_path.exists():
        return []
    
    user_pattern = config.materials.naming_pattern or ""
    allowed_exts = set()
    for ft in config.materials.file_types:
        ft_lower = ft.lower().strip(".")
        for category, exts in SUPPORTED_FILE_TYPES.items():
            for ext in exts:
                if ext.strip(".") == ft_lower:
                    allowed_exts.add(ext)
    
    if not allowed_exts:
        for exts in SUPPORTED_FILE_TYPES.values():
            allowed_exts.update(exts)
    
    participants = {}
    unmatched_files = []
    
    # 여러 패턴 시도 목록
    patterns = []
    if user_pattern:
        patterns.append(user_pattern)
    patterns += [
        r"(\d+)\.\s*(.+)",          # "1. 홍길동"
        r"(\d+)[-_]\s*(.+)",        # "1-홍길동" 또는 "1_홍길동"
        r"(\d+)_(\d+)_(.+)",        # "1001_000149_생기부" (첫 숫자가 번호)
        r"(\d+)\s+(.+)",            # "1 홍길동"
        r"(\d+)(.*)",               # "1234어떤텍스트" (숫자로 시작하면 무조건)
    ]
    
    for file_path in folder_path.rglob("*"):
        if not file_path.is_file():
            continue
        
        ext = file_path.suffix.lower()
        if ext not in allowed_exts:
            continue
        
        stem = file_path.stem
        matched = False
        
        for pat in patterns:
            m = re.match(pat, stem)
            if m:
                num = int(m.group(1))
                # 이름 추출: 그룹이 3개면 마지막, 2개면 두번째
                if m.lastindex >= 3:
                    name = m.group(3).strip()
                elif m.lastindex >= 2:
                    name = m.group(2).strip()
                else:
                    name = f"참가자 {num}"
                # 이름이 비어있거나 숫자만이면 기본값
                if not name or name.replace("_", "").replace("-", "").strip() == "":
                    name = f"참가자 {num}"
                matched = True
                break
        
        if not matched:
            unmatched_files.append(file_path)
            continue
        
        if num not in participants:
            participants[num] = {
                "number": num,
                "name": name,
                "files": [],
            }
        
        file_category = "other"
        for cat, exts in SUPPORTED_FILE_TYPES.items():
            if ext in exts:
                file_category = cat
                break
        
        participants[num]["files"].append({
            "path": str(file_path),
            "name": file_path.name,
            "type": file_category,
            "ext": ext,
            "size_mb": round(file_path.stat().st_size / 1024 / 1024, 1),
        })
    
    # 일부 파일만 이름 규칙에 맞지 않아도 숨기지 않는다.
    # 전부 미인식이면 기존처럼 1번부터 임시 번호를 붙이고, 일부만 미인식이면
    # 실제 명렬·인식 번호 뒤의 임시 번호를 붙여 교사가 연결을 바로잡게 한다.
    if unmatched_files:
        if participants:
            used_numbers = list(participants) + [
                student.number for student in config.roster_students
            ]
            first_unmatched_number = max(used_numbers, default=0) + 1
        else:
            first_unmatched_number = 1
        for offset, file_path in enumerate(sorted(unmatched_files)):
            i = first_unmatched_number + offset
            ext = file_path.suffix.lower()
            file_category = "other"
            for cat, exts in SUPPORTED_FILE_TYPES.items():
                if ext in exts:
                    file_category = cat
                    break
            participants[i] = {
                "number": i,
                "name": file_path.stem,
                "files": [{
                    "path": str(file_path),
                    "name": file_path.name,
                    "type": file_category,
                    "ext": ext,
                    "size_mb": round(file_path.stat().st_size / 1024 / 1024, 1),
                }],
            }
    
    result = sorted(participants.values(), key=lambda x: x["number"])
    return result


def _scan_uploads(config: ProjectConfig) -> list[dict]:
    """프로젝트 materials 폴더에서 업로드된 파일 탐색"""
    materials_dir = PROJECTS_DIR / config.id / "materials"
    if not materials_dir.exists():
        return []
    
    # 업로드 폴더를 folder_path처럼 취급
    temp_config = ProjectConfig(
        materials=type(config.materials)(
            source_type="folder",
            folder_path=str(materials_dir),
            file_types=config.materials.file_types,
            naming_pattern=config.materials.naming_pattern,
        )
    )
    # categories 등 나머지 필드는 필요 없으므로 기본값 사용
    return _scan_folder(temp_config)


def get_participant_files(config: ProjectConfig, participant_num: int) -> dict:
    """특정 참가자의 파일 목록 반환"""
    materials = find_materials(config)
    for p in materials:
        if p["number"] == participant_num:
            return p
    return {"number": participant_num, "name": f"참가자 {participant_num}", "files": []}


def save_uploaded_file(config: ProjectConfig, file_storage, filename: str) -> str:
    """업로드된 파일 저장"""
    materials_dir = PROJECTS_DIR / config.id / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    
    save_path = materials_dir / filename
    file_storage.save(str(save_path))
    return str(save_path)

"""AI 제공자 업로드용 파일 준비와 문서 변환."""
from __future__ import annotations

import shutil
import time
from pathlib import Path


def convert_document_to_pdf(src_path: Path, pdf_path: Path) -> None:
    """한컴오피스 COM을 사용해 HWP/HWPX/DOC/DOCX를 PDF로 변환한다."""
    import win32com.client

    hwp = None
    try:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        hwp.XHwpWindows.Item(0).Visible = False
        hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
        try:
            hwp.SetAltMode(0)
        except Exception:
            pass
        hwp.Open(str(src_path), "HWP", "forceopen:true;versionwarning:false")
        hwp.HAction.GetDefault("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
        hwp.HParameterSet.HFileOpenSave.filename = str(pdf_path)
        hwp.HParameterSet.HFileOpenSave.Format = "PDF"
        hwp.HAction.Execute("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
        for _ in range(30):
            time.sleep(0.5)
            if pdf_path.exists() and pdf_path.stat().st_size > 500:
                break
        hwp.Clear(False)
        if not pdf_path.exists() or pdf_path.stat().st_size <= 500:
            raise RuntimeError(f"문서 PDF 변환 실패: {src_path.name}")
    finally:
        if hwp:
            try:
                hwp.Quit()
            except Exception:
                pass


def prepare_upload_file(source: Path, temp_dir: Path, index: int) -> Path:
    """한글 경로와 지원되지 않는 문서 형식을 업로드 가능한 임시 파일로 바꾼다."""
    source = source.resolve()
    ext = source.suffix.lower()
    if ext in (".hwp", ".hwpx", ".doc", ".docx"):
        target = temp_dir / f"document_{index}.pdf"
        convert_document_to_pdf(source, target)
        return target
    target = temp_dir / f"upload_{index}{ext}"
    shutil.copy2(source, target)
    return target


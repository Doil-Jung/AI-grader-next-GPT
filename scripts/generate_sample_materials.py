"""AI 채점기 수동 검증용 가상 문제지·기준표·통합 답안 PDF를 생성한다."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "pdf"
FONT_REGULAR = Path(r"C:\Windows\Fonts\malgun.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Malgun", str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont("MalgunBold", str(FONT_BOLD)))


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "KTitle", parent=base["Title"], fontName="MalgunBold",
            fontSize=20, leading=28, alignment=TA_CENTER, textColor=colors.HexColor("#1f3b64"),
        ),
        "subtitle": ParagraphStyle(
            "KSubtitle", parent=base["Normal"], fontName="Malgun",
            fontSize=10, leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#52606d"),
        ),
        "heading": ParagraphStyle(
            "KHeading", parent=base["Heading2"], fontName="MalgunBold",
            fontSize=13, leading=19, spaceBefore=8, spaceAfter=8, textColor=colors.HexColor("#1f3b64"),
        ),
        "body": ParagraphStyle(
            "KBody", parent=base["BodyText"], fontName="Malgun",
            fontSize=10.5, leading=18, wordWrap="CJK", spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "KSmall", parent=base["BodyText"], fontName="Malgun",
            fontSize=8.5, leading=13, wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "KTable", parent=base["BodyText"], fontName="Malgun",
            fontSize=8.2, leading=12, wordWrap="CJK",
        ),
        "table_bold": ParagraphStyle(
            "KTableBold", parent=base["BodyText"], fontName="MalgunBold",
            fontSize=8.2, leading=12, wordWrap="CJK",
        ),
    }


def footer(canvas_obj, doc) -> None:
    canvas_obj.saveState()
    canvas_obj.setFont("Malgun", 8)
    canvas_obj.setFillColor(colors.HexColor("#6b7280"))
    canvas_obj.drawString(18 * mm, 12 * mm, "AI 채점기 테스트용 가상 자료 - 실제 학생 정보가 아닙니다.")
    canvas_obj.drawRightString(192 * mm, 12 * mm, f"{doc.page}쪽")
    canvas_obj.restoreState()


def build_question_pdf(path: Path) -> None:
    st = styles()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
    )
    story = [
        Paragraph("중학교 과학 서술형 평가 - 테스트 문제지", st["title"]),
        Paragraph("총 15점 · 3문항 · AI 채점기 기능 검증용", st["subtitle"]),
        Spacer(1, 8 * mm),
        Paragraph("응시 안내", st["heading"]),
        Paragraph("각 문항의 풀이 과정과 과학적 근거를 문장으로 작성하세요. 계산 문항에는 식과 단위를 쓰고, 실험 설계 문항에는 변인을 구분해 쓰세요.", st["body"]),
        Spacer(1, 5 * mm),
        Paragraph("1번. 광합성의 물질 변화와 에너지 전환 (4점)", st["heading"]),
        Paragraph("식물이 광합성을 할 때 사용되는 물질과 생성되는 물질을 쓰고, 빛에너지가 어떤 형태의 에너지로 전환되는지 설명하시오. 엽록체 또는 엽록소의 역할도 포함하시오.", st["body"]),
        Spacer(1, 15 * mm),
        Paragraph("2번. 힘과 가속도 (5점)", st["heading"]),
        Paragraph("질량이 2 kg인 수레에 진행 방향으로 4 N의 알짜힘이 작용한다. 수레의 가속도를 식과 단위를 포함하여 구하시오. 질량은 그대로이고 알짜힘만 8 N으로 증가할 때 가속도가 어떻게 변하는지도 설명하시오.", st["body"]),
        PageBreak(),
        Paragraph("3번. 소금 농도와 물의 끓는점 실험 설계 (6점)", st["heading"]),
        Paragraph("물에 녹인 소금의 농도가 물의 끓는점에 미치는 영향을 알아보려 한다. 검증 가능한 가설을 세우고, 독립 변인과 종속 변인을 구분하시오. 공정한 비교를 위해 같게 유지해야 할 조건을 두 가지 이상 제시하고, 측정의 신뢰도를 높이는 방법을 설명하시오.", st["body"]),
        Spacer(1, 20 * mm),
        Paragraph("답안 작성란", st["heading"]),
        Paragraph("실제 시험에서는 별도 답안지를 사용합니다. 함께 제공된 통합 답안 PDF는 가상 학생 5명의 답안을 학생당 2쪽씩 순서대로 스캔한 예시입니다.", st["body"]),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def build_rubric_pdf(path: Path) -> None:
    st = styles()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm,
        topMargin=16 * mm, bottomMargin=20 * mm,
    )
    p = lambda text, bold=False: Paragraph(text, st["table_bold" if bold else "table"])
    data = [
        [p("문항", True), p("모범답안 핵심", True), p("부분점 기준", True), p("검토 필요 사례", True)],
        [
            p("1번<br/>4점", True),
            p("이산화탄소와 물을 사용하여 포도당과 산소를 만들며, 엽록소가 빛을 흡수한다. 빛에너지는 포도당에 저장되는 화학에너지로 전환된다."),
            p("· 반응물·생성물 2점<br/>· 빛→화학에너지 1점<br/>· 엽록체/엽록소 역할 1점"),
            p("물질 방향을 반대로 씀, 호흡과 혼동, 과학적으로 타당한 대안 표현"),
        ],
        [
            p("2번<br/>5점", True),
            p("F=ma이므로 a=F/m=4/2=2 m/s²이다. 8 N이면 a=8/2=4 m/s²로 두 배가 되며 힘과 같은 방향이다."),
            p("· F=ma 식 1점<br/>· 2 m/s² 계산 2점<br/>· 힘 두 배→가속도 두 배 1점<br/>· 방향·단위 1점"),
            p("계산 과정 누락, 단위 누락, 알짜힘과 개별 힘 혼동"),
        ],
        [
            p("3번<br/>6점", True),
            p("소금 농도가 높을수록 끓는점이 높아질 것이라는 가설을 세운다. 독립 변인은 소금 농도, 종속 변인은 끓는 온도이다. 물의 양·용기·가열 세기 등을 통제하고 반복 측정 후 평균을 낸다."),
            p("· 검증 가능 가설 1점<br/>· 독립 변인 1점<br/>· 종속 변인 1점<br/>· 통제 변인 2개 이상 2점<br/>· 반복·평균 1점"),
            p("변인 구분이 불명확함, 통제 조건 부족, 답안이 잘리거나 판독 불가"),
        ],
    ]
    table = Table(data, colWidths=[17 * mm, 62 * mm, 58 * mm, 45 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f1f5f9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story = [
        Paragraph("서술형 평가 채점기준표 - 교사용 테스트 자료", st["title"]),
        Paragraph("AI가 이 문서를 우선 기준으로 구조화하는지 확인하기 위한 가상 자료", st["subtitle"]),
        Spacer(1, 7 * mm),
        table,
        Spacer(1, 8 * mm),
        Paragraph("채점 운영 원칙", st["heading"]),
        Paragraph("동일한 과학 개념을 정확히 표현한 대안 답안은 용어가 다르더라도 인정합니다. 판독 불가, 문항 대응 불명확, 기준에 없는 타당한 접근은 AI가 임의로 단정하지 않고 교사 검토 대상으로 표시해야 합니다. 모든 AI 점수는 교사 승인 전 임시 점수입니다.", st["body"]),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


STUDENTS = [
    {
        "number": 1, "name": "가상학생1", "level": "정답 충실형 (예상 15점)",
        "answers": [
            "1번: 광합성에서는 이산화탄소와 물을 사용해 포도당과 산소를 만든다. 엽록체의 엽록소가 빛을 흡수하며, 빛에너지는 포도당에 저장되는 화학에너지로 전환된다.",
            "2번: F=ma이므로 a=F/m=4 N/2 kg=2 m/s²이다. 힘과 같은 방향으로 가속한다. 힘이 8 N이면 a=8/2=4 m/s²이므로 가속도는 두 배가 된다.",
            "3번: 소금 농도가 높을수록 물의 끓는점이 높아질 것이다. 독립 변인은 소금 농도, 종속 변인은 끓기 시작한 온도이다. 물의 양, 용기, 가열 장치와 세기를 같게 한다. 각 농도를 3회 반복해 평균을 비교한다.",
        ],
    },
    {
        "number": 2, "name": "가상학생2", "level": "부분정답형 (예상 11점 내외)",
        "answers": [
            "1번: 이산화탄소와 물로 포도당과 산소를 만든다. 엽록소가 빛을 받는다. 에너지 전환에 대한 설명은 쓰지 못했다.",
            "2번: F=ma, a=4/2=2 m/s²이다. 힘이 8 N이 되면 가속도도 커지지만 정확한 값은 계산하지 않았다.",
            "3번: 소금이 많을수록 끓는점이 높아질 것이다. 바꾸는 것은 소금 농도이고 측정하는 것은 끓는 온도이다. 물의 양과 가열 세기를 같게 한다. 반복 측정에 대한 설명은 없다.",
        ],
    },
    {
        "number": 3, "name": "가상학생3", "level": "오개념 포함형 (예상 4~6점)",
        "answers": [
            "1번: 식물은 산소를 마시고 이산화탄소를 내보내는 것이 광합성이다. 에너지는 열에너지로 바뀐다.",
            "2번: 4 N에 2 kg을 곱해서 가속도는 8 m/s²이다. 힘이 두 배면 질량도 두 배가 된다.",
            "3번: 소금을 넣은 물과 넣지 않은 물을 끓여 온도를 잰다. 소금의 양을 바꾸고 온도를 측정한다. 물의 양이나 용기는 따로 맞추지 않았다.",
        ],
    },
    {
        "number": 4, "name": "가상학생4", "level": "대안표현 우수형 (예상 14점 내외)",
        "answers": [
            "1번: 잎의 엽록체가 햇빛을 받아 CO₂와 H₂O를 당과 O₂로 바꾼다. 햇빛의 에너지는 당 분자의 결합에 저장된다. 즉 빛에너지가 화학에너지로 저장된다.",
            "2번: 뉴턴 제2법칙에 따라 4=2a, 따라서 a=2 m/s²이다. 8 N일 때는 8=2a이므로 a=4 m/s²이고 진행 방향으로 가속한다.",
            "3번: 소금 농도가 커지면 끓기 시작하는 온도도 올라갈 것으로 예상한다. 농도를 0%, 2%, 4%, 6%로 바꾸고 끓는 온도를 측정한다. 물 200 mL, 같은 비커, 같은 가열판을 사용한다. 여러 번 측정해야 한다고 썼지만 평균 계산은 언급하지 않았다.",
        ],
    },
    {
        "number": 5, "name": "가상학생5", "level": "백지·판독불가형 (교사 검토 필요)",
        "answers": [
            "1번: (작성하지 않음)",
            "2번: 잘 모르겠습니다.",
            "3번: [스캔 원본의 오른쪽 부분이 잘리고 번져 있어 답안 일부를 판독할 수 없음] 소금을 넣고 온도를… 이후 내용 판독 불가.",
        ],
    },
]


def draw_wrapped(c: canvas.Canvas, text: str, x: float, y: float, width_chars: int = 54) -> float:
    chunks = []
    remaining = text
    while remaining:
        chunks.append(remaining[:width_chars])
        remaining = remaining[width_chars:]
    c.setFont("Malgun", 11)
    for chunk in chunks:
        c.drawString(x, y, chunk)
        y -= 7 * mm
    return y


def answer_page_header(c: canvas.Canvas, student: dict, page_in_student: int) -> None:
    width, height = A4
    c.setFillColor(colors.HexColor("#1f3b64"))
    c.rect(0, height - 28 * mm, width, 28 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("MalgunBold", 16)
    c.drawString(18 * mm, height - 17 * mm, "과학 서술형 평가 답안지")
    c.setFont("Malgun", 9)
    c.drawRightString(width - 18 * mm, height - 16 * mm, "가상 자료 / 실제 학생 아님")
    c.setFillColor(colors.black)
    c.setFont("MalgunBold", 11)
    c.drawString(18 * mm, height - 38 * mm, f"학생번호 {student['number']}    이름 {student['name']}")
    c.setFont("Malgun", 9)
    c.drawRightString(width - 18 * mm, height - 38 * mm, f"학생별 {page_in_student}/2쪽 · {student['level']}")
    c.setStrokeColor(colors.HexColor("#94a3b8"))
    c.line(18 * mm, height - 42 * mm, width - 18 * mm, height - 42 * mm)


def build_integrated_answers_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    for student in STUDENTS:
        answer_page_header(c, student, 1)
        y = height - 55 * mm
        c.setFont("MalgunBold", 12)
        c.drawString(18 * mm, y, "1번 답안")
        y = draw_wrapped(c, student["answers"][0], 18 * mm, y - 10 * mm)
        y -= 10 * mm
        c.setFont("MalgunBold", 12)
        c.drawString(18 * mm, y, "2번 답안")
        draw_wrapped(c, student["answers"][1], 18 * mm, y - 10 * mm)
        c.setFont("Malgun", 8)
        c.setFillColor(colors.HexColor("#6b7280"))
        c.drawString(18 * mm, 12 * mm, f"통합 PDF 원본 {student['number'] * 2 - 1}쪽")
        c.drawRightString(width - 18 * mm, 12 * mm, "분할 설정: 학생당 2쪽")
        c.showPage()

        answer_page_header(c, student, 2)
        y = height - 55 * mm
        c.setFont("MalgunBold", 12)
        c.drawString(18 * mm, y, "3번 답안")
        draw_wrapped(c, student["answers"][2], 18 * mm, y - 10 * mm)
        c.setStrokeColor(colors.HexColor("#cbd5e1"))
        for line_y in range(int(55 * mm), int(height - 120 * mm), int(10 * mm)):
            c.line(18 * mm, line_y, width - 18 * mm, line_y)
        c.setFont("Malgun", 8)
        c.setFillColor(colors.HexColor("#6b7280"))
        c.drawString(18 * mm, 12 * mm, f"통합 PDF 원본 {student['number'] * 2}쪽")
        c.drawRightString(width - 18 * mm, 12 * mm, "분할 설정: 학생당 2쪽")
        c.showPage()
    c.save()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    register_fonts()
    build_question_pdf(OUTPUT_DIR / "서술형_테스트_문제지.pdf")
    build_rubric_pdf(OUTPUT_DIR / "서술형_테스트_채점기준표.pdf")
    build_integrated_answers_pdf(OUTPUT_DIR / "서술형_테스트_통합답안_5명.pdf")
    print(f"생성 완료: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

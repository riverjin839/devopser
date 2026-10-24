# N(id, type, label, sublabel, col, row, tag=None)  type: backend frontend database messagebus security cloud external
# E(from, to, label=None, variant=None|"emphasis"|"dashed", fromSide=None, toSide=None)
# hero = 강조(진녹 그라데이션) 노드 id 목록. 3열 이하, stepx 250 / stepy 150 기본
SPECS = {
    "ch01-07-fn-timeline": dict(
        title="FN 사례 - 진단 과정 순서", hero=["judge"],
        nodes=[N("visit", "external", "내원 · 문진", "건강검진 접수", 0, 0, "1"),
               N("ct", "backend", "영상 촬영", "흉부 CT", 1, 0, "2"),
               N("infer", "backend", "AI 모델 추론", "암 확률 0.38", 2, 0, "3"),
               N("judge", "security", "임계값 판정", "0.38 < 0.5 → 음성", 2, 1, "FN"),
               N("doctor", "frontend", "의사 판독", "AI 음성 참고 · 정밀검사 생략", 1, 1, "4"),
               N("notify", "frontend", "결과 통보", "정상 · 1년 뒤 재검", 0, 1, "5"),
               N("symptom", "external", "증상 발현", "6개월 후 통증", 0, 2, "6"),
               N("confirm", "database", "재검 · 확진", "암 3기 진행", 1, 2, "7"),
               N("review", "messagebus", "원인 분석", "FN → 임계값 하향", 2, 2, "8")],
        edges=[E("visit", "ct", "검사 오더"), E("ct", "infer", "영상 입력"),
               E("infer", "judge", "점수", "emphasis"), E("judge", "doctor", "음성 표시", "emphasis"),
               E("doctor", "notify", "판독 완료", "emphasis"), E("notify", "symptom", "치료 공백", "dashed"),
               E("symptom", "confirm", "재방문"), E("confirm", "review", "사후 검토")]),
}


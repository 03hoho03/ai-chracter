"""검사 규칙 목록과 모호 후보 판정. 규칙은 슬롯이 아니라 코어 소유다 — 여러 슬롯을 함께 읽는 규칙을 슬롯이 가지면 슬롯끼리
묶인다. 규칙마다 읽는 슬롯을 선언하고, 그 슬롯이 등록부에 없으면 검사 틀이 건너뛴다. 목록은 차단 넷과 판정 호출이 필요 없는
경고들이다 — 모델 판정의 충돌·판정 실패 경고는 검사 틀에 주입하는 판정 함수(`judge.build_judge`)가 낸다."""

from api.novel_bible.core.contracts import Rule
from api.novel_bible.rules.blocking import BLOCKING_RULES
from api.novel_bible.rules.judge import build_judge
from api.novel_bible.rules.warnings import WARNING_RULES

RULES: list[Rule] = [*BLOCKING_RULES, *WARNING_RULES]

__all__ = ["RULES", "build_judge"]

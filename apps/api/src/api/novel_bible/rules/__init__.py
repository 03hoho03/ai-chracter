"""검사 규칙 목록. 규칙은 슬롯이 아니라 코어 소유다 — 여러 슬롯을 함께 읽는 규칙을 슬롯이 가지면 슬롯끼리 묶인다. 규칙마다
읽는 슬롯을 선언하고, 그 슬롯이 등록부에 없으면 검사 틀이 건너뛴다. 규칙 코드가 들어오기 전까지 비어 있다."""

from api.novel_bible.core.contracts import Rule

RULES: list[Rule] = []

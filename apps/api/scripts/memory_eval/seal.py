"""봉인 전 시험 절반 계산 금지.

사전 등록은 개발 절반으로 모든 선택을 끝내고 그 런의 판을 봉인(sha256 기록)한 뒤에만 시험 절반을 한 번 계산하게 정했다. 시험
절반의 recall·정답 포함률·추출 보존율·판정·출처 귀속을 내는 명령은 이 확인을 먼저 지난다: 사전 등록 문서 첫 줄이 이번 런의
봉인 판(`SEALED_EDITION`)이고, 그 문서의 sha256 이 해시 파일에 적힌 값이고, 실행자가 인자로 준 해시와도 같아야 한다. 개발
절반만 계산할 때는 확인하지 않는다.

판 번호는 측정마다 하나다. 앞 측정의 판(v2·v3)은 그 측정이 시험 절반을 이미 한 번 계산해 소진했으므로, 그 판의 문서로는 더 이상
시험 절반을 열 수 없다 — 같은 시험 문항을 다시 열어 고른 규칙은 시험 절반이 개발 절반이 된 셈이라 일반화 근거가 되지 못한다.
다음 측정은 `SEALED_EDITION` 한 곳만 새 판으로 바꾼다(머리글 검사와 거부 문구가 이 값에서 나온다)."""

import hashlib
import re
from pathlib import Path

# 원자료 폴더 안의 사전 등록 문서 파일 이름(해시 파일은 같은 이름의 `.sha256`).
PREREGISTRATION_FILE = "preregistration.md"  # cite-ok: 하네스가 여는 원자료 폴더의 실제 파일 이름이다
# 이번 측정이 봉인할 사전 등록 판. 첫 줄의 `(판)`·`(판.1)` 꼴만 받는다.
SEALED_EDITION = "v4"
_SEALED_HEADER = re.compile(rf"\({re.escape(SEALED_EDITION)}(\.\d+)?\)")


def require_seal(splits: set[str], preregistration: Path, *, seal_sha: str | None) -> None:
    if "test" not in splits:
        return
    if not seal_sha:
        raise SystemExit(f"시험 절반은 {SEALED_EDITION} 봉인 해시(--seal-sha)가 있어야 계산한다")
    first_line = preregistration.read_text(encoding="utf-8").splitlines()[0] if preregistration.exists() else ""
    if not _SEALED_HEADER.search(first_line):
        raise SystemExit(f"사전 등록 첫 줄이 이번 런의 봉인 판({SEALED_EDITION})이 아니다: {first_line!r}")
    actual = hashlib.sha256(preregistration.read_bytes()).hexdigest()
    sha_file = preregistration.with_suffix(".sha256")
    recorded = {
        parts[0]
        for line in (sha_file.read_text(encoding="utf-8").splitlines() if sha_file.exists() else [])
        if len(parts := line.split()) == 2 and parts[1].endswith(preregistration.name)
    }
    if actual not in recorded:
        raise SystemExit(
            "사전 등록 문서의 sha256 이 해시 파일에 기록된 값과 다르다(봉인 뒤 문서가 바뀌었거나 아직 기록 전)"
        )
    if seal_sha != actual:
        raise SystemExit("준 봉인 해시가 지금 사전 등록 문서의 sha256 과 다르다")

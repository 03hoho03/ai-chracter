"""운영·격리 두 지문 파일(fingerprint.sql 출력)을 (테이블, 행 키, 열) 단위로 비교한다.

복제 때 일부러 바꾼 열(작가·소유자·생성 요청 id·카운트·고정 댓글·세트 게시 시각)은
"의도한 차이"로 따로 세고, 그 밖의 차이·한쪽에만 있는 행·열은 전부 불일치로 낸다.
불일치가 하나라도 있으면 종료 코드 1.

사용: python compare_fingerprint.py <운영 지문> <격리 지문>
"""

import sys
from pathlib import Path

INTENDED = {
    ("contents", "creator_user_id"),
    ("contents", "view_count"),
    ("contents", "like_count"),
    ("contents", "chat_count"),
    ("contents", "pinned_comment_id"),
    ("assets", "owner_user_id"),
    ("assets", "request_id"),
    ("prompt_sets", "published_at"),
}


def load(path: str) -> tuple[dict[tuple[str, str, str], str], list[str]]:
    rows: dict[tuple[str, str, str], str] = {}
    meta: list[str] = []
    for line in Path(path).read_text().splitlines():
        parts = line.split("\t")
        if parts[0] == "fp_meta":
            meta = parts[1:]
        elif parts[0] == "fp":
            rows[(parts[1], parts[2], parts[3])] = parts[4]
    return rows, meta


def main() -> None:
    prod, prod_meta = load(sys.argv[1])
    iso, iso_meta = load(sys.argv[2])
    print(f"meta 운영={prod_meta} 격리={iso_meta}")
    tables = sorted({k[0] for k in prod} | {k[0] for k in iso})
    bad = 0
    for t in tables:
        pk = {k for k in prod if k[0] == t}
        ik = {k for k in iso if k[0] == t}
        rows_p = {k[1] for k in pk}
        rows_i = {k[1] for k in ik}
        same = intended = 0
        for k in sorted(pk | ik):
            if prod.get(k) == iso.get(k):
                same += 1
            elif (t, k[2]) in INTENDED and k in prod and k in iso:
                intended += 1
                print(f"  의도\t{t}\t{k[1]}\t{k[2]}")
            else:
                bad += 1
                print(f"  불일치\t{t}\t{k[1]}\t{k[2]}\t운영={prod.get(k, '<없음>')}\t격리={iso.get(k, '<없음>')}")
        print(f"{t}\t행 운영 {len(rows_p)} / 격리 {len(rows_i)}\t값 같음 {same} · 의도한 차이 {intended}")
    print(f"불일치 {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

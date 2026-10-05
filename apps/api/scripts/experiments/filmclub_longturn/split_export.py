"""운영 내보내기 출력(prod_export.sql + fingerprint.sql 을 한 접속으로 돌린 psql 출력)을 나눈다.

입력 한 레코드는 "<태그>\t<값>" 으로 시작하고, json_agg 가 배열 원소 사이에 줄바꿈을 넣으므로
다음 태그 줄이 나올 때까지의 줄을 이어 붙인다(psql 명령 완료 줄은 버린다). 지문 줄(fp)은 탭 구분 그대로 따로 모은다.

사용: python split_export.py <raw.tsv> <출력 디렉터리>
  → <출력>/<테이블>.json, check.json, prod-fingerprint.tsv
"""

import json
import re
import sys
from pathlib import Path

TAG = re.compile(r"^([a-z_]+)\t")
# tuples_only 여도 psql 은 명령 완료 줄을 찍는다. JSON 줄은 이 단어 하나로 끝나지 않는다.
PSQL_STATUS = {"SET", "BEGIN", "ROLLBACK"}


def main() -> None:
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, list[str]]] = []
    for line in raw.read_text().splitlines():
        if line in PSQL_STATUS:
            continue
        m = TAG.match(line)
        if m:
            records.append((m.group(1), [line[m.end():]]))
        elif records:
            records[-1][1].append(line)
    fp_lines: list[str] = []
    for tag, parts in records:
        if tag in ("fp", "fp_meta"):
            fp_lines.append(f"{tag}\t{parts[0]}")
            continue
        # 두 번째 파일의 \pset 안내 문구가 앞 레코드 뒤에 붙으므로 첫 JSON 값만 읽는다.
        value, _ = json.JSONDecoder().raw_decode("\n".join(parts))
        (out / f"{tag}.json").write_text(json.dumps(value, ensure_ascii=False, indent=1))
        if isinstance(value, list):
            print(f"{tag}\t{len(value)}")
    (out / "prod-fingerprint.tsv").write_text("\n".join(fp_lines) + "\n")
    print(f"fp\t{sum(1 for x in fp_lines if x.startswith('fp\t'))}")


if __name__ == "__main__":
    main()

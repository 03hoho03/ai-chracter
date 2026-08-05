"""장르별 시드 콘텐츠 정의와 그것을 DB 에 밀어 넣는 도구 모음.

콘텐츠 본문은 코드가 아니라 `data/stories/{slug}.json` / `data/characters/{slug}.json`
데이터 파일이고, 이 패키지는 그 파일을 읽고(`loader`) 결정적 UUID 를 붙여(`ids`)
시드하는 부분만 담당한다. `scripts/seed_dev.py` 가 유일한 진입점이다.
"""

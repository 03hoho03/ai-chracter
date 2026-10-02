"""판정 리플레이 — 운영 판정·발행 심사 문안 스냅숏과 설계 장면으로 서버와 같은 판정 프롬프트를 렌더해, 모델·사고 설정별로
`generate_structured` 를 반복 호출하고 결과를 JSONL 로 남긴다. 실행은 `scripts/replay_judgments.py`, 집계는
`scripts/analyze_judgment_replay.py`."""

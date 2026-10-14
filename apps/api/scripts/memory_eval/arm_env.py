"""2차 런 두 갈래(하네스 갈래 id `A2`·`B2`)의 측정 서버 env 표. 키 값은 넣지 않는다 — 서버는 `.env` 의 키를 그대로 읽는다.

공통: 장면 추출·회상·사실 추출을 켜고, 판정·요약·두 추출 모델을 haiku 로, 호출 위치마다 Anthropic 직결을 배정한다(미리보기
판정 셋 포함 — 빠지면 그 호출이 기본 구현인 Bedrock 으로 가 다른 Haiku 버전이 섞인다). Gemini·Bedrock 은 쓰지 않으므로 Gemini
키는 기동 검증만 지나는 자리값, Bedrock 자격은 비운다. 갈래 A2 = 장면 회상(보통 턴 상한 조정·사용자 꼬리표는 같은 이미지의
코드 기본값), B2 = A2 + 사실 섹션 주입 — 두 갈래의 차이는 `MEMORY_FACTS_INJECT` 한 줄이다. 사실은 두 갈래 모두 추출한다.

`PROMPT_DUMP_PATH` 는 프로브가 프로브 폴더마다 넣는다(이 표에서 주면 그 값으로 한 줄을 더한다).

사실 계층의 설정 이름(`MEMORY_FACTS_EXTRACT`·`MEMORY_FACT_MODEL`·`MEMORY_FACTS_INJECT`)과 호출 위치 `chat_memory_fact` 는 운영
사실 계층 코드가 따라야 할 이름이다 — 그 코드가 없는 이미지는 모르는 호출 위치 배정을 기동 검증에서 거부한다."""

ANTHROPIC_CALL_SITES = (
    "chat_generate",
    "replay_generate",
    "chat_stat_judgment",
    "chat_ending_judgment",
    "chat_situational_image",
    "chat_media_book_image",
    "chat_memory_summary",
    "chat_memory_episode",
    "chat_memory_fact",
    "preview_stat_judgment",
    "preview_ending_judgment",
    "preview_media_book_image",
)

COMMON_ENV: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC_HAIKU_MODEL_ID", "claude-haiku-5-5"),
    ("STAT_JUDGMENT_MODEL", "haiku"),
    ("ENDING_JUDGMENT_MODEL", "haiku"),
    ("IMAGE_JUDGMENT_MODEL", "haiku"),
    ("MEMORY_SUMMARY_MODEL", "haiku"),
    ("MEMORY_EPISODES_EXTRACT", "true"),
    ("MEMORY_EPISODE_MODEL", "haiku"),
    ("MEMORY_EPISODES_RECALL", "true"),
    ("MEMORY_FACTS_EXTRACT", "true"),
    ("MEMORY_FACT_MODEL", "haiku"),
    ("LLM_CALL_SITE_BACKENDS", ",".join(f"{site}:anthropic" for site in ANTHROPIC_CALL_SITES)),
    ("CHAT_PREMIUM_MODELS_ENABLED", "true"),
    ("GEMINI_API_KEY", "dummy-not-used"),
    ("BEDROCK_ACCESS_KEY_ID", ""),
    ("BEDROCK_SECRET_ACCESS_KEY", ""),
)

ARM_ENV: dict[str, tuple[tuple[str, str], ...]] = {
    "A2": (("MEMORY_FACTS_INJECT", "false"),),
    "B2": (("MEMORY_FACTS_INJECT", "true"),),
}


def env_pairs(arm: str, *, prompt_dump: str | None = None) -> list[tuple[str, str]]:
    if arm not in ARM_ENV:
        raise SystemExit(f"env 표가 있는 갈래는 {sorted(ARM_ENV)} 뿐이다: {arm}")
    pairs = list(COMMON_ENV) + list(ARM_ENV[arm])
    if prompt_dump:
        pairs.append(("PROMPT_DUMP_PATH", prompt_dump))
    return pairs


def env_text(arm: str, *, prompt_dump: str | None = None) -> str:
    """`--server-env` 로 줄 수 있는 KEY=VALUE 파일 본문."""
    head = [f"# 2차 런 갈래 {arm} 측정 서버 env — 키 값은 넣지 않는다(.env 그대로)"]
    if not prompt_dump:
        head.append("# PROMPT_DUMP_PATH 는 프로브가 프로브 폴더마다 넣는다")
    return "\n".join(head + [f"{k}={v}" for k, v in env_pairs(arm, prompt_dump=prompt_dump)]) + "\n"

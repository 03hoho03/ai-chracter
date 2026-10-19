"""2차 런 두 갈래(하네스 갈래 id `A2`·`B2`)의 측정 서버 env 표. 키 값은 넣지 않는다 — 서버는 `.env` 의 키를 그대로 읽는다.

공통: 장면 추출·회상·사실 추출을 켜고, 판정·요약·두 추출 모델을 haiku 로, 호출 위치마다 Anthropic 직결을 배정한다(미리보기
판정 셋 포함 — 빠지면 그 호출이 기본 구현인 Bedrock 으로 가 다른 Haiku 버전이 섞인다). Gemini·Bedrock 은 쓰지 않으므로 Gemini
키는 기동 검증만 지나는 자리값, Bedrock 자격은 비운다. 갈래 A2 = 장면 회상(보통 턴 상한 조정·사용자 꼬리표는 같은 이미지의
코드 기본값), B2 = A2 + 사실 섹션 주입 — 두 갈래의 차이는 `MEMORY_FACTS_INJECT` 한 줄이다. 사실은 두 갈래 모두 추출한다.

`PROMPT_DUMP_PATH` 는 프로브가 프로브 폴더마다 넣는다(이 표에서 주면 그 값으로 한 줄을 더한다).

사실 계층의 설정 이름(`MEMORY_FACTS_EXTRACT`·`MEMORY_FACT_MODEL`·`MEMORY_FACTS_INJECT`)과 호출 위치 `chat_memory_fact` 는 운영
사실 계층 코드가 따라야 할 이름이다 — 그 코드가 없는 이미지는 모르는 호출 위치 배정을 기동 검증에서 거부한다."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory_eval.embed_offline import HybridParams

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
    # 기억 스위치가 동작하는 방의 범위(두 레인의 Opus 방). 측정 생성 모델이 Opus 라 운영 코드 기본값과 같지만, 기본값이 바뀐
    # 서버로 돌려도 측정 조건이 같도록 적어 둔다. 이 설정이 없는 서버는 모르는 환경변수로 버린다.
    ("MEMORY_MODEL_SCOPE", "opus"),
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


# 묶음 1 측정의 여섯 갈래(하네스 갈래 id 는 `b1-` 를 붙인다 — 2차 런의 `B2` 와 뜻이 달라 같은 이름을 쓰지 않는다). 갈래마다
# 아래 다섯 스위치만 다르고 나머지 줄은 같다. 스위치 이름은 앱 설정 칸 이름을 대문자로 한 것이다 — 서버는 모르는 환경변수를
# 조용히 버려, 이름이 틀린 갈래는 그 스위치를 끈 채로 돈다(임베딩 줄까지 모든 줄이 앱 설정 칸임을 테스트가 본다). 요약 표기가
# 켜진 갈래는 B 계열 템플릿(같은 투입에서 요약 글만 표기 판으로 바꾼 것)에서 돈다.
BUNDLE1_SWITCHES = (
    "MEMORY_EPISODES_RECALL",
    "MEMORY_SUMMARY_SECRET_MARKING",
    "MEMORY_KNOWLEDGE_FILTER",
    "MEMORY_FACTS_INJECT",
    "MEMORY_EMBED_RECALL",
)
BUNDLE1_ARMS: dict[str, tuple[bool, ...]] = {
    "b1-A0": (False, False, False, False, False),
    # A0 + 요약 비밀 표기: 회상을 보류해도 요약 표기를 켤 수 있는지 본다. 지식 범위 필터는 운영에서 요약 표기와 한 단계로 켜므로
    # 같이 켠다 — 사실 주입·회상이 꺼져 있어 이 갈래에서 필터는 생성 프롬프트를 바꾸지 않는다.
    "b1-A0M": (False, True, True, False, False),
    "b1-A1": (True, False, False, False, False),
    "b1-B1": (True, True, True, False, False),
    "b1-B2": (True, True, True, True, True),
    "b1-B1E": (True, True, True, False, True),
}
# 캐릭터 대본은 다인물 비밀 범주가 없어 스위치 하나짜리 비교(B1·B1E)의 판별력이 거의 없다 — 그 둘을 뺀 네 갈래만 돈다. A0M 은
# 회상 없이 요약 표기를 켜는 길이 두 레인 모두에 걸리므로 캐릭터에서도 돈다.
CHARACTER_LANE_ARMS = ("b1-A0", "b1-A0M", "b1-A1", "b1-B2")
# 투입하는 동안 언제나 켜 두는 줄은 임베딩 쓰기다. 투입이 벡터를 쓴 채로 돌아야 어느 갈래로 재든 같은 행에서 출발한다.
BUNDLE1_COMMON_EXTRA = (("MEMORY_EMBED_WRITE", "true"),)
B_SERIES_SUFFIX = "-b"
# 대화 기록 뒤에 실리는 섹션의 스위치(설정 칸 이름). B 계열 갈래를 이 셋을 끈 채 다시 렌더한 점(`-bare` 갈래)이 그 갈래 자신의
# 앞 두 캐시 블록 비교 상대다 — 두 계열은 요약 글이 달라 계열 사이 블록 비교는 정의상 어긋난다.
POST_HISTORY_SWITCHES = ("memory_episodes_recall", "memory_facts_inject", "memory_embed_recall")
BARE_SUFFIX = "-bare"


def template_series(arm: str) -> str:
    """갈래가 도는 템플릿 계열 — 요약 표기 스위치가 켜졌으면 B, 아니면 A."""
    if arm not in BUNDLE1_ARMS:
        raise SystemExit(f"묶음 1 갈래는 {sorted(BUNDLE1_ARMS)} 뿐이다: {arm}")
    return "B" if BUNDLE1_ARMS[arm][BUNDLE1_SWITCHES.index("MEMORY_SUMMARY_SECRET_MARKING")] else "A"


def series_label(base_label: str, arm: str) -> str:
    """갈래가 복원할 템플릿의 단계 이름. A 계열은 투입 단계 이름 그대로, B 계열은 꼬리를 붙인 이름이다 — 갈래가 다른 계열의
    템플릿을 복원할 길을 이름으로 막는다."""
    return base_label + (B_SERIES_SUFFIX if template_series(arm) == "B" else "")


def require_lane_arm(arm: str, lane: object) -> None:
    """심기 표의 레인(`lane` 칸)이 있어야 하고, 캐릭터 레인은 `CHARACTER_LANE_ARMS` 갈래만 받는다."""
    template_series(arm)
    if lane not in ("story", "character"):
        raise SystemExit(f"묶음 1 갈래는 심기 표의 레인이 story·character 중 하나여야 한다: {lane!r}")
    if lane == "character" and arm not in CHARACTER_LANE_ARMS:
        raise SystemExit(f"캐릭터 레인 대본은 {list(CHARACTER_LANE_ARMS)} 갈래만 돈다: {arm}")


def bundle1_env_pairs(
    arm: str,
    *,
    lane: str,
    embed_model: str,
    embed_dims: int,
    recall: "HybridParams",
    embed_timeout_ms: int,
    prompt_dump: str | None = None,
) -> list[tuple[str, str]]:
    """묶음 1 갈래의 측정 서버 env. 레인은 심기 표의 `lane` 이고, 캐릭터 레인은 `CHARACTER_LANE_ARMS` 갈래만 받는다. 임베딩 모델·차원과 하이브리드
    회상 설정(`memory_embed_recall_*`)은 개발 절반에서 정한 값을 실행마다 준다(기본값을 두면 확정 전 값으로 조용히 돈다). 모든
    갈래가 같은 줄을 받는다 — 임베딩 읽기가 꺼진 갈래에서는 회상 설정이 쓰이지 않을 뿐이다. 질의 임베딩 시간 상한
    (`MEMORY_EMBED_RECALL_TIMEOUT_MS`)도 실행마다 받아 싣는다 — 측정 서버가 실제로 쓴 값이 env 에 남게. 긴 방 df 상한이 없음(None)이면
    그 줄을 싣지 않는다 — 앱 설정은 env 글로 없음을 받지 못해(빈 글도 정수 해석에서 거부된다) 줄을 빼야 앱 기본값(없음)으로 돈다.
    줄을 빼면 서버가 `.env`·실행 환경의 값을 읽으므로, 띄우기 전에 `leaked_embed_keys` 로 막는다."""
    require_lane_arm(arm, lane)
    if not embed_model.strip():
        raise SystemExit("임베딩 모델(MEMORY_EMBED_MODEL)을 정해 줘야 한다")
    if embed_dims <= 0:
        raise SystemExit(f"임베딩 차원(MEMORY_EMBED_DIMS)을 정해 줘야 한다: {embed_dims}")
    if embed_timeout_ms <= 0:
        raise SystemExit(f"질의 임베딩 시간 상한(MEMORY_EMBED_RECALL_TIMEOUT_MS)을 정해 줘야 한다: {embed_timeout_ms}")
    switches = dict(zip(BUNDLE1_SWITCHES, BUNDLE1_ARMS[arm], strict=True))
    pairs = [(k, v) for k, v in COMMON_ENV if k not in switches]
    pairs += [*BUNDLE1_COMMON_EXTRA, ("MEMORY_EMBED_MODEL", embed_model), ("MEMORY_EMBED_DIMS", str(embed_dims))]
    pairs += [(name.upper(), str(value)) for name, value in recall.config().items() if value is not None]
    pairs.append(("MEMORY_EMBED_RECALL_TIMEOUT_MS", str(embed_timeout_ms)))
    pairs += [(k, "true" if on else "false") for k, on in switches.items()]
    if prompt_dump:
        pairs.append(("PROMPT_DUMP_PATH", prompt_dump))
    return pairs


# 임베딩 쓰기·읽기 설정 줄의 머리. 묶음 1 env 가 싣지 않은 이 머리의 키는 서버가 `.env`·실행 환경에서 읽는다.
EMBED_ENV_PREFIX = "MEMORY_EMBED_"


def env_file_keys(text: str) -> set[str]:
    """`.env` 꼴 글의 키(주석·빈 줄 제외, `export ` 머리 허용)."""
    keys = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.removeprefix("export ").partition("=")[0].strip())
    return keys


def leaked_embed_keys(overrides: Mapping[str, str], *, env_file: str, environ: Mapping[str, str]) -> list[str]:
    """측정 서버 env(`overrides`)가 정하지 않은 임베딩 설정 키 가운데 `.env`(`env_file`)나 실행 환경(`environ`)에 있는 것 — 서버가
    그 값을 읽어 갈래 설정(대표적으로 df 상한 '없음')이 조용히 바뀐다. 실행 명령의 값이 `.env` 를 이기므로 정한 키는 괜찮다."""
    present = env_file_keys(env_file) | set(environ)
    return sorted(k for k in present if k.startswith(EMBED_ENV_PREFIX) and k not in overrides)

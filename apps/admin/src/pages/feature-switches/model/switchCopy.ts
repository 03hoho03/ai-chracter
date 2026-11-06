import type {
  FeatureSwitchName,
  FeatureSwitchWarning,
  ReadOnlyFeatureSwitchName,
  ReadOnlySwitchReason,
} from "./types";

/** 화면의 묶음. 서버는 묶음을 모른다 — 사람이 읽는 배치라 화면이 가진다. */
export type SwitchGroup =
  | "money-terms"
  | "novel-public"
  | "novel-tools"
  | "memory-prompt"
  | "memory-after-turn"
  | "memory-visible"
  | "image"
  | "chat-infra";

/** 묶음 순서는 위험이 큰 것부터다(돈·약관이 맨 위). 순서를 따로 배열로 두지 않고 이 `Record` 의 칸(`order`)으로 둔다 — 따로
 * 둔 배열은 묶음이 늘어도 컴파일 에러가 나지 않아, 빠진 묶음 하나가 화면에서 조용히 사라진다. */
export const SWITCH_GROUP_COPY = {
  "money-terms": {
    title: "돈·약관",
    note: "클로버를 깎고 주는 경로와 약관에 묶인 스위치예요. 결제·본인인증 게이트는 키 설정까지 본 실제 상태를 함께 보여요.",
    order: 1,
  },
  "novel-public": {
    title: "노벨(공개 소설)",
    note: "정책 스위치는 노벨 공개가 꺼져 있어도 탈퇴·삭제·이용제한 환급·판매 중단 동작을 바꿔요.",
    order: 2,
  },
  "novel-tools": {
    title: "소설(작가 도구)",
    note: "구성 흐름·여러 문단 수정은 소설화가 꺼져 있으면 효과가 없어요. 삽화는 작가의 붙이기만 소설화를 따르고, 노벨 독자의 그림 표시·삽화 업로드·표지 이미지 삭제 막기는 소설화와 무관해요.",
    order: 3,
  },
  "memory-prompt": {
    title: "기억 · 프롬프트에 싣기",
    note: "회상·사실 주입·지식 범위 필터·비밀 표기는 기억 사용 범위(MEMORY_MODEL_SCOPE) 안 방에서만 돌아요. 생성 윈도우가 꺼지면 이 묶음과 '턴 뒤 쌓기'가 전부 멈춰요. 기억 스위치를 덮어쓰면 턴 기록에 그 값이 남지 않아, 리플레이 도구가 .env 값으로 재현해 그 턴과 어긋나요.",
    order: 4,
  },
  "memory-after-turn": {
    title: "기억 · 턴 뒤 쌓기",
    note: "요약 접기 뒤 백그라운드로 쌓아요. 생성 윈도우가 꺼지면 접기가 없어 돌지 않아요.",
    order: 5,
  },
  "memory-visible": {
    title: "기억 · 보기와 기록",
    note: "사용자에게 보이거나 기록을 남겨요. 켜기 전에 처리방침 게시가 먼저인 스위치가 있어요.",
    order: 6,
  },
  image: { title: "이미지", note: null, order: 7 },
  "chat-infra": { title: "채팅 모델 · 인프라", note: "전부 .env 로만 바꿔요.", order: 8 },
} satisfies Record<SwitchGroup, { title: string; note: string | null; order: number }>;

function isSwitchGroup(value: string): value is SwitchGroup {
  return value in SWITCH_GROUP_COPY;
}

export const SWITCH_GROUPS_IN_ORDER: readonly SwitchGroup[] = Object.keys(SWITCH_GROUP_COPY)
  .filter(isSwitchGroup)
  .sort((a, b) => SWITCH_GROUP_COPY[a].order - SWITCH_GROUP_COPY[b].order);

type AdjustableSwitchCopy = {
  group: SwitchGroup;
  label: string;
  /** 이 이름을 주어로 쓸 때의 조사("생성 윈도우가 꺼져 있어…"). 받침에 따라 갈려 이름마다 적는다. */
  subjectParticle: "이" | "가";
  description: string;
};

/** 버튼으로 바꾸는 스위치의 사람이 읽는 이름·설명. 키는 서버 이름 목록이라 서버에 스위치가 늘면 여기서 컴파일 에러가 난다.
 * 묶음 안 행 순서는 이 객체에 적은 순서다. */
export const ADJUSTABLE_SWITCH_COPY = {
  clover_ledger_paused: {
    group: "money-terms",
    label: "클로버 정지",
    subjectParticle: "가",
    description: "클로버를 깎거나 주는 경로를 503 으로 멈춰요. 환급·결제 완료 확인·웹훅·탈퇴는 그대로예요.",
  },
  payments_enabled: {
    group: "money-terms",
    label: "결제",
    subjectParticle: "가",
    description: "클로버 구매(주문)를 열어요. 포트원 키와 본인인증 설정이 모두 있어야 실제로 열려요.",
  },
  identity_gate_enabled: {
    group: "money-terms",
    label: "본인인증 게이트",
    subjectParticle: "가",
    description: "미인증 회원의 미션 보상을 막고, 기본 모델(Gemini) 채팅에서 클로버가 모자라면 인증을 요구해요.",
  },
  novel_public_enabled: {
    group: "novel-public",
    label: "노벨 공개",
    subjectParticle: "가",
    description:
      "모든 회원에게 노벨 목록·읽기·구매를 열고, 소설을 노벨에 공개하게 해요. 끄면 노벨이 모든 회원에게 닫히고(404) 공개 상태·구매는 남아요.",
  },
  novel_public_policy_v2_enabled: {
    group: "novel-public",
    label: "노벨 공개 정책",
    subjectParticle: "이",
    description: "첫 공개 운영자 승인·연재권 잠금·구매자 보호·6화부터 무료/유료 선택. 끄면 옛 약관 동작이에요.",
  },
  novelize_enabled: {
    group: "novel-tools",
    label: "소설화",
    subjectParticle: "가",
    description: "대화를 소설의 장으로 옮겨 쓰는 기능의 전역 스위치. 명단·계정별 허용과 함께 있어야 써요.",
  },
  novelize_outline_flow_enabled: {
    group: "novel-tools",
    label: "소설 구성 흐름",
    subjectParticle: "이",
    description: "구간 선택 → 구성안 → 화. 켜면 옛 이어 쓰기가 409 예요.",
  },
  novelize_multi_block_edit_enabled: {
    group: "novel-tools",
    label: "여러 문단 수정",
    subjectParticle: "이",
    description: "떨어진 문단 여럿을 한 번에 AI 수정해요. 끈 뒤에도 받은 수정안은 쓰거나 버릴 수 있어요.",
  },
  novel_illustrations_enabled: {
    group: "novel-tools",
    label: "소설 화 삽화",
    subjectParticle: "가",
    description: "화에 삽화를 붙이고 노벨 화에 그림을 보여요.",
  },
  memory_window_generation: {
    group: "memory-prompt",
    label: "생성 윈도우",
    subjectParticle: "가",
    description: "긴 방의 생성 프롬프트에서 요약이 덮은 원문을 빼고 요약을 실어요. 끄면 기억 기능이 전부 멈춰요.",
  },
  memory_window_ending_judgment: {
    group: "memory-prompt",
    label: "엔딩 판정 윈도우",
    subjectParticle: "가",
    description: "엔딩 판정에 대화 전체 대신 요약과 최근 원문을 실어요.",
  },
  memory_window_image_judgment: {
    group: "memory-prompt",
    label: "그림 판정 윈도우",
    subjectParticle: "가",
    description: "상황 이미지·미디어 북 칸 판정에 최근 원문만 실어요.",
  },
  memory_episodes_recall: {
    group: "memory-prompt",
    label: "장면 회상",
    subjectParticle: "이",
    description: "매 턴 이어질 장면 기억을 생성 프롬프트에 실어요.",
  },
  memory_facts_inject: {
    group: "memory-prompt",
    label: "사실 주입",
    subjectParticle: "이",
    description: "매 턴 관계·사실 기억을 생성 프롬프트에 실어요.",
  },
  memory_knowledge_filter: {
    group: "memory-prompt",
    label: "지식 범위 필터",
    subjectParticle: "가",
    description: "이번 장면에 없는 인물만 아는 비밀을 사실 섹션에서 빼요.",
  },
  memory_summary_secret_marking: {
    group: "memory-prompt",
    label: "요약 비밀 표기",
    subjectParticle: "가",
    description: "요약 접기 프롬프트에 비밀 표기 지시와 인물 목록을 실어요.",
  },
  memory_episodes_extract: {
    group: "memory-after-turn",
    label: "장면 추출",
    subjectParticle: "이",
    description: "요약이 접은 구간을 장면 기억으로 뽑아요.",
  },
  memory_facts_extract: {
    group: "memory-after-turn",
    label: "사실 추출",
    subjectParticle: "이",
    description: "요약이 접은 구간을 관계·사실 기억으로 뽑아요.",
  },
  memory_impressions_write: {
    group: "memory-after-turn",
    label: "인상 쓰기",
    subjectParticle: "가",
    description: "접기 몇 번마다 인물 사이 감정 흐름(인상)을 쌓아요. 프롬프트에는 싣지 않아요.",
  },
  memory_items_visible: {
    group: "memory-visible",
    label: "기억 보기",
    subjectParticle: "가",
    description: "방 주인에게 장면·사실 기억 목록·잊게 하기·요약 다시 만들기를 열어요.",
  },
  memory_impressions_visible: {
    group: "memory-visible",
    label: "인상 보기",
    subjectParticle: "가",
    description: "기억 보기 목록에 인상을 실어요.",
  },
  stat_event_log: {
    group: "memory-visible",
    label: "스탯 판정 이벤트 기록",
    subjectParticle: "이",
    description: "턴 기록에 스탯 판정 규칙·폭을 남겨요. 프롬프트·스탯 값은 같아요.",
  },
  local_image_reference_enabled: {
    group: "image",
    label: "참조 이미지",
    subjectParticle: "가",
    description: "본인이 만든 생성 이미지를 참조로 집 PC 에 실어요.",
  },
} satisfies Record<FeatureSwitchName, AdjustableSwitchCopy>;

/** `.env` 로만 바꾸는 스위치의 사람이 읽는 이름·설명. 버튼이 없는 이유는 서버가 코드로 주고 문장은 `READ_ONLY_REASON_TEXT` 다. */
export const READ_ONLY_SWITCH_COPY = {
  creator_payout_enabled: {
    group: "money-terms",
    label: "크리에이터 정산",
    description: "크리에이터 정산 신청을 열어요. 본인인증 설정이 없으면 켜도 닫혀요.",
  },
  novelize_premium_models_enabled: {
    group: "novel-tools",
    label: "소설 상위 모델",
    description: "소설 장을 상위 모델로 써요.",
  },
  novelize_worker_enabled: {
    group: "novel-tools",
    label: "소설화 워커",
    description: "소설화 작업을 api 밖 워커 컨테이너가 돌려요.",
  },
  novel_bible_enabled: {
    group: "novel-tools",
    label: "소설 정본 기억",
    description: "확정한 화에서 사건·사실·지식을 쌓는 엔진이에요.",
  },
  memory_embed_recall: {
    group: "memory-prompt",
    label: "임베딩 회상",
    description: "질의 임베딩으로 회상·사실 순위를 섞어요.",
  },
  memory_embed_write: {
    group: "memory-after-turn",
    label: "임베딩 쓰기",
    description: "장면·사실 행을 Voyage 로 임베딩해 채워요.",
  },
  chat_premium_models_enabled: {
    group: "chat-infra",
    label: "채팅 상위 모델",
    description: "로그인 회원에게 채팅 상위 모델을 열어요.",
  },
  llm_credential_pool_enabled: {
    group: "chat-infra",
    label: "Claude 자격 목록",
    description: "Anthropic 직결 호출이 어드민의 Claude 자격 목록에서 키를 골라 써요. 꺼지면 env 키 하나로 가요.",
  },
  expose_api_docs: {
    group: "chat-infra",
    label: "API 문서 노출",
    description: "/docs·/openapi.json 을 열어요. 운영에서는 켜지 않아요.",
  },
  session_cookie_secure: {
    group: "chat-infra",
    label: "세션 쿠키 Secure",
    description: "세션 쿠키에 Secure 를 붙여요.",
  },
} satisfies Record<ReadOnlyFeatureSwitchName, { group: SwitchGroup; label: string; description: string }>;

export const READ_ONLY_REASON_TEXT = {
  "startup-check": "켤 때 필요한 자격·키를 서버가 기동 때 확인해요. 덮어쓰기로 켜면 그 확인을 건너뛰어요.",
  "worker-startup": "소설화 워커가 기동 때 한 번 읽어요. 바꾸려면 워커 재기동과 기동 검증이 필요해요.",
  "deploy-starts-worker": "교체 스크립트가 이 값을 보고 워커 컨테이너를 띄워요. 워커 없이 켜면 작업이 만료 환불로 끝나요.",
  "separate-cron-process":
    "월 확정 크론이 따로 뜬 프로세스에서 읽어 덮어쓰기를 보지 못하고, 켤 때 크론 설치가 함께 필요해요.",
  "app-creation": "앱을 만들 때 한 번만 읽어요.",
  infrastructure: "기능이 아니라 쿠키 보안 인프라 설정이에요.",
} satisfies Record<ReadOnlySwitchReason, string>;

/** 저장은 됐지만 운영자가 알아야 할 것. 반영 간격(초)은 서버가 주는 값을 받는다. */
export const WARNING_TEXT = {
  "refund-started-during-pause": () =>
    "정지를 켜는 사이 환불이 하나 시작됐어요. 정지 중에는 그 환불을 마무리할 수 없어요 — 잠깐 끄고 마무리한 뒤 다시 켜세요.",
  "self-refresh-failed": (refreshSeconds: number) =>
    `저장은 됐지만 이 서버의 즉시 반영이 실패했어요. ${refreshSeconds}초마다 다시 읽으니 곧 반영돼요.`,
} satisfies Record<FeatureSwitchWarning, (refreshSeconds: number) => string>;

export function isFeatureSwitchName(value: string): value is FeatureSwitchName {
  return value in ADJUSTABLE_SWITCH_COPY;
}

function isReadOnlyFeatureSwitchName(value: string): value is ReadOnlyFeatureSwitchName {
  return value in READ_ONLY_SWITCH_COPY;
}

/** 화면에 그리는 순서(묶음 순서 → 묶음 안 적은 순서)의 버튼 대상 이름. 이력 거르기의 옵션과 라우트 검증이 이것을 쓴다. */
export const FEATURE_SWITCH_NAMES: readonly FeatureSwitchName[] = SWITCH_GROUPS_IN_ORDER.flatMap((group) =>
  Object.keys(ADJUSTABLE_SWITCH_COPY)
    .filter(isFeatureSwitchName)
    .filter((name) => ADJUSTABLE_SWITCH_COPY[name].group === group),
);

/** `.env` 로만 바꾸는 스위치 이름 — 묶음 안 행 순서는 `READ_ONLY_SWITCH_COPY` 에 적은 순서다. */
export const READ_ONLY_SWITCH_NAMES: readonly ReadOnlyFeatureSwitchName[] =
  Object.keys(READ_ONLY_SWITCH_COPY).filter(isReadOnlyFeatureSwitchName);

/** 이력·모르는 덮어쓰기처럼 아무 이름이나 올 수 있는 자리의 사람 이름. 이 화면이 모르는 이름이면 `null`. */
export function switchLabelOf(name: string): string | null {
  if (isFeatureSwitchName(name)) return ADJUSTABLE_SWITCH_COPY[name].label;
  if (isReadOnlyFeatureSwitchName(name)) return READ_ONLY_SWITCH_COPY[name].label;
  return null;
}

export function switchSubjectOf(name: FeatureSwitchName): string {
  const copy = ADJUSTABLE_SWITCH_COPY[name];
  return `${copy.label}${copy.subjectParticle}`;
}

export function onOffText(value: boolean): string {
  return value ? "켜짐" : "꺼짐";
}

/** 저장이 언제 어디까지 닿는지 — 화면 설명과 확인 모달이 함께 쓴다. 간격은 서버가 주는 값이고, 아직 못 받았으면 수를 말하지
 * 않는다. */
export function reflectSentence(refreshSeconds: number | undefined): string {
  const within = refreshSeconds === undefined ? "몇 초 안에" : `약 ${refreshSeconds}초 안에`;
  return `저장하면 모든 서버 프로세스와 소설화 워커가 ${within} 새 값을 봐요. 이미 시작된 요청·작업은 시작 때 값으로 끝까지 돌아요.`;
}

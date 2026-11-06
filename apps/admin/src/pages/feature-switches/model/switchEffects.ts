import { onOffText, switchSubjectOf } from "./switchCopy";
import type {
  AdminAdjustableSwitch,
  AdminFeatureSwitchListResponse,
  FeatureSwitchName,
  ReadOnlyFeatureSwitchName,
} from "./types";

/** 확인 모달 문장이 읽는 지금 값. 다른 스위치의 실효 값은 목록 응답에서 온다. */
export type EffectContext = {
  /** 다른 서버 프로세스가 저장을 보기까지 길어야 걸리는 초(서버가 주는 값). */
  refreshSeconds: number;
  isOn: (name: FeatureSwitchName | ReadOnlyFeatureSwitchName) => boolean;
  /** 결제·본인인증 게이트의 비어 있는 설정 키 이름. 다른 스위치는 빈 목록이다. */
  missingSettings: readonly string[];
};

/** 목록 응답에서 `item` 의 확인 모달이 읽을 지금 값을 꺼낸다. */
export function effectContextOf(list: AdminFeatureSwitchListResponse, item: AdminAdjustableSwitch): EffectContext {
  const values = new Map<string, boolean>([
    ...list.adjustable.map((other): [string, boolean] => [other.name, other.effectiveValue]),
    ...list.readOnly.map((other): [string, boolean] => [other.name, other.value]),
  ]);
  return {
    refreshSeconds: list.refreshIntervalSeconds,
    isOn: (name) => values.get(name) === true,
    missingSettings: item.effectiveState?.missingSettings ?? [],
  };
}

/** 늘 같은 문장이거나, 지금 값에 따라 달라지는 문장. 함수가 `null` 을 주면 그 줄은 싣지 않는다. */
type EffectLine = string | ((context: EffectContext) => string | null);

type DirectionCopy = {
  /** 바뀌는 것. */
  changes: readonly EffectLine[];
  /** 되돌릴 수 없는 것 — 따로 제목을 달아 보인다. */
  irreversible?: readonly EffectLine[];
  /** 알아 둘 것. */
  notes?: readonly EffectLine[];
  /** 효과 없음·선행 조건처럼 지금 값 때문에 생기는 경고. */
  warnings?: readonly EffectLine[];
  /** 확정 버튼을 `destructive` 틴트로 그린다 — 효과가 가장 넓거나 되돌릴 수 없는 두 방향에만. */
  tone?: "destructive";
};

export type ResolvedEffects = {
  changes: string[];
  irreversible: string[];
  notes: string[];
  warnings: string[];
  tone: "default" | "destructive";
};

/** 켜는 스위치가 기대는 상위 스위치가 꺼져 있으면 켜도 돌지 않는다는 경고. 저장은 막지 않는다 — 실효 값만 바뀐다. */
function inertWhenOff(...parents: FeatureSwitchName[]): EffectLine {
  return (context) => {
    const off = parents.find((parent) => !context.isOn(parent));
    return off === undefined ? null : inertWhenOffText(off);
  };
}

function inertWhenOffText(parent: FeatureSwitchName): string {
  return `${switchSubjectOf(parent)} 꺼져 있어 켜도 돌지 않아요 — 실효 값만 켜짐으로 바뀌어요.`;
}

function missingSettingsLine(consequence: string): EffectLine {
  return ({ missingSettings }) =>
    missingSettings.length === 0 ? null : `지금 비어 있는 설정: ${missingSettings.join(", ")} — ${consequence}`;
}

const ADMIN_TAB_NOTE =
  "어드민 노벨·작품 조치의 환급 문구가 이 값을 따라요 — 이 탭은 저장 뒤 바로 바뀌고, 다른 어드민 탭은 새로고침해야 바뀌어요.";
const LEFTOVER_ROWS_LINE = "이미 쌓인 행은 남고 새로 쌓지 않아요.";
const EXTRACT_CATCH_UP_NOTE =
  "켠 직후에는 기존 방의 밀린 접기를 턴마다 하나씩 소화해 따라잡을 때까지 추출 원가가 일시적으로 많아요.";
const STAT_LOG_SAME_NOTE = "켜도 꺼도 판정·프롬프트·스탯 값은 같아요 — 기록만 달라져요.";

/** 스위치마다 켜기·끄기 확인 모달에 싣는 결과 문장. 키가 서버 이름 목록이라 스위치가 늘면 컴파일 에러로 빠짐이 잡힌다.
 * 효과 없음 조건은 서버 코드의 의존을 이 화면이 손으로 들고 있는 것이다 — 경고일 뿐 저장을 막지 않는다. */
const SWITCH_EFFECTS = {
  clover_ledger_paused: {
    on: {
      tone: "destructive",
      changes: [
        "클로버를 새로 깎거나 주는 경로가 503 CLOVER_PAUSED 로 멈춰요 — 모든 차감(채팅·이미지의 유료 갈래, 요약 다시 만들기, 소설화 작업 시작, 노벨 소장), 미션·출석 수령, 어드민 지급·회수, 어드민 결제 환불 실행, 주문 생성.",
        "레이트리밋 면제 계정이 아닌 회원의 채팅 턴은 전부 503 이에요.",
        "그대로인 것: 면제 계정의 기본 모델(Gemini) 채팅 턴(상위 모델 턴은 면제 계정도 503), 무료 토큰 이미지, 모든 환급, 결제 완료 확인·웹훅(포트원 콘솔 취소 포함), 만료 크론, 탈퇴.",
      ],
      notes: [
        ({ refreshSeconds }) =>
          `저장 뒤 길어야 약 ${refreshSeconds}초 동안 다른 서버 프로세스는 옛 값을 보고, 그 전에 시작된 요청은 끝까지 옛 값으로 돌아요 — 그 사이 차감·지급이 몇 건 더 일어날 수 있어요.`,
        "클로버 단위 전환 같은 마이그레이션의 정지 확인은 이 덮어쓰기가 아니라 .env 의 CLOVER_LEDGER_PAUSED 를 봐요 — 그런 작업에는 .env 줄이 따로 필요해요.",
        "진행 중인 환불이 있으면 서버가 켜기를 거절해요(정지 중에는 그 환불을 마무리하는 라우트도 막혀서예요).",
      ],
    },
    off: { changes: ["클로버를 깎고 주는 경로가 다시 열려요."] },
  },
  payments_enabled: {
    on: {
      changes: [
        "클로버 구매(주문 생성)가 열리고, 웹 충전 화면은 다음에 가격·상품을 다시 받을 때 구매를 보여요.",
        "결제는 늘 본인인증(만 19세 확인)을 거쳐요 — 본인인증 게이트·레이트리밋 면제와 무관해요.",
        "실제로 열리려면 포트원 키 넷(상점 id·결제 채널키·API 비밀·웹훅 비밀)과 본인인증 설정 넷(상점 id·본인인증 채널키·API 비밀·CI HMAC 키)이 모두 있어야 해요.",
      ],
      notes: ["결제를 켜는 날은 약관 개정 시행일과 묶여 있어요 — 게시된 약관이 결제를 적고 있는지 확인하세요."],
      warnings: [missingSettingsLine("켜도 결제는 닫힌 채예요.")],
    },
    off: {
      changes: [
        "주문 생성이 503 PAYMENTS_UNAVAILABLE 이 되고, 웹 충전 화면은 다음 조회 때 구매를 닫아요.",
        "웹훅은 계속 처리해요 — 진행 중 결제와 포트원 콘솔 취소를 맞춰요.",
        "본인인증 게이트와 크리에이터 정산도 실제로 꺼져 있으면 마이페이지의 본인인증 시작도 503 이 돼요.",
      ],
      notes: ["닫는 기간이 길어지면 게시된 약관의 결제 안내와 다른지 확인하세요."],
    },
  },
  identity_gate_enabled: {
    on: {
      changes: [
        "본인인증을 안 한 회원(레이트리밋 면제 제외)은 미션 보상을 못 받고, 기본 모델(Gemini) 채팅에서 클로버가 모자랄 때 429 대신 403 IDENTITY_VERIFICATION_REQUIRED 를 받아요(상위 모델 채팅은 그대로 429). 가진 클로버로는 계속 대화해요. 이미지·소설·작품 만들기는 막지 않아요.",
        "출석 수령은 이 게이트와 무관하게 늘 본인인증 회원만 받아요.",
      ],
      notes: [
        "이 게이트는 미인증 회원이 쓸 수 있는 범위를 줄이는 변경이라 약관 조항 개정이 필요해요 — 게시된 약관이 이 게이트를 적고 있을 때만 켜요.",
        "실제로 걸리려면 본인인증 설정 넷이 있어야 해요.",
      ],
      warnings: [missingSettingsLine("켜도 게이트는 걸리지 않아요.")],
    },
    off: {
      changes: [
        "미인증 회원도 미션 보상을 받고, 기본 모델(Gemini) 채팅에서 클로버가 모자라면 다시 429 예요.",
        "결제·크리에이터 정산도 실제로 꺼져 있으면 마이페이지의 본인인증 시작이 503 이 돼요.",
      ],
      notes: ["게이트를 적은 약관이 시행 중이면 약관과 실제 동작이 달라져요."],
    },
  },
  novel_public_enabled: {
    on: {
      changes: ["모든 회원에게 노벨 목록·읽기·구매를 열고, 소설을 노벨에 공개하게 해요."],
      warnings: [
        (context) =>
          context.isOn("novelize_enabled")
            ? null
            : "소설화가 꺼져 있어 새 공개·다시 공개는 안 되지만, 이미 공개된 노벨의 목록·읽기·구매는 열려요.",
      ],
    },
    off: {
      changes: [
        "모든 회원에게 노벨 탭·목록·읽기·구매·댓글이 닫히고(404), 소장자는 화를 열면 410(잠시 쉬는 중)을 받아요. 공개·다시 공개는 403 이에요.",
        "공개 상태·구매·댓글은 남아 다시 켜면 그대로 돌아와요.",
      ],
    },
  },
  novel_public_policy_v2_enabled: {
    on: {
      changes: [
        "첫 공개 운영자 승인·연재권 잠금·산 사람 보호·6화부터 무료/유료 선택이 켜져요.",
        "이미 공개한 화를 다시 낼 때 변경 요약이 필요해져, 공개 화면을 연 채인 작가는 422 를 받을 수 있어요.",
      ],
      notes: [
        "개정 약관(승인 반려의 이의제기 경로, 연재권 조항)이 시행되고, 어드민 승인 대기열과 작가의 대기·반려 화면이 배포되고, 처리방침에 탈퇴 뒤 남는 정보가 개정·시행된 뒤에 켜요.",
        ADMIN_TAB_NOTE,
      ],
    },
    off: {
      tone: "destructive",
      changes: [
        "첫 공개가 운영자 승인 없이 자동 글 심사만 통과하면 바로 열려요. 남은 승인 대기 행은 독자에게 안 보인 채 남고, 작가가 다시 신청하면 처음 공개처럼 바로 공개돼요.",
        "연재권 잠금이 꺼져요 — 원작자가 허락을 거두거나 원작을 비공개로 돌리거나 탈퇴하면 이미 독자에게 보인 소설도 다음 화가 막히고, 원작자 탈퇴 뒤의 새 소설화도 다시 돼요.",
        "6화부터 유료로 저장되고 무료 전환은 409, 무료로 나간 번호도 지키지 않아요.",
      ],
      irreversible: [
        "산 사람 보호가 함께 꺼져요. 켜져 있는 동안 거둔 소설·게시자가 정지된 소설·원작자 정지로 일괄 제한된 원작의 소설·숨긴 소설(판매된 소설 삭제, 게시자 탈퇴)·판매를 멈춘 노벨·판매만 멈추기로 제한·삭제한 원작의 소설의 소장자는 끄는 순간 환급 없이 410 을 받아요.",
        "판매를 멈춘 노벨은 끈 뒤 재개할 수 없어요(409) — 다시 팔 노벨은 끄기 전에 재개하세요.",
        "끈 동안 게시자가 탈퇴하면 판매된 소설까지 환급 없이 지워져요. 판매된 소설 삭제는 다시 진짜 삭제 + 환급이고, 운영자 제재는 환급하지 않아요.",
        "운영 문서(DEPLOY.md 「노벨(공개 소설) 켜기 · 끄기」 절)는 끄기를 롤백 때만 하고, 끄기 전에 그런 소장자가 몇 명인지 세라고 적어요.",
      ],
      notes: [ADMIN_TAB_NOTE],
    },
  },
  novelize_enabled: {
    on: { changes: ["명단·계정별 허용이 있는 계정이 대화를 소설의 장으로 옮겨 쓸 수 있어요."] },
    off: { changes: ["모든 소설 화면·API 가 403 이고 허용 행은 남아요(다시 켜면 돌아와요)."] },
  },
  novelize_outline_flow_enabled: {
    on: {
      changes: ["다음 화를 구간 선택 → 구성안 → 화 흐름으로 만들고, 옛 이어 쓰기는 409 예요."],
      notes: ["개정 처리방침(구간 선택·구성안 항목) 게시 뒤, 화면이 구성 흐름으로만 다음 화를 만들게 된 뒤에 켜요."],
      warnings: [inertWhenOff("novelize_enabled")],
    },
    off: { changes: ["구성 흐름 라우트가 404 가 되고 옛 이어 쓰기가 다시 열려요."] },
  },
  novelize_multi_block_edit_enabled: {
    on: {
      changes: ["떨어진 문단 여럿을 한 번에 AI 수정할 수 있어요."],
      warnings: [inertWhenOff("novelize_enabled")],
    },
    off: { changes: ["요청·재검사 라우트가 404 이고, 이미 받은 수정안은 쓰거나 버릴 수 있어요."] },
  },
  novel_illustrations_enabled: {
    on: {
      changes: ["화에 삽화를 붙이고 노벨 화에 그림을 보여요. 표지로 쓴 이미지는 삭제가 409 가 돼요."],
      notes: [
        "개정 처리방침(삽화 항목) 게시 뒤 켜요.",
        "삽화를 심사할 프롬프트 세트(프롬프트 관리의 「발행 검열」 레인)가 없으면 서버가 켜기를 거절해요.",
      ],
      warnings: [
        (context) =>
          context.isOn("novelize_enabled")
            ? null
            : "소설화가 꺼져 있어 작가의 삽화 붙이기만 막히고, 노벨 독자의 그림 표시·표지 이미지 삭제 409·삽화 업로드는 켜져요.",
      ],
    },
    off: {
      changes: [
        "삽화 붙이기 API 가 404, 삽화 업로드가 422, 작가의 화·개정 응답과 노벨 독자의 화에서 그림이 빠지고, 표지로 쓴 이미지를 다시 지울 수 있어요(표지가 빔).",
        "이미 개정에 붙은 배치는 이어져요.",
      ],
    },
  },
  memory_window_generation: {
    on: {
      changes: ["긴 방의 생성 프롬프트가 요약과 최근 원문으로 돌아가고, 멈춰 있던 기억 스위치들이 각자 값대로 다시 돌아요."],
    },
    off: {
      changes: [
        "긴 방의 생성 프롬프트에 요약이 덮은 원문까지 전부 실어요(요약 품질 사고 때 되돌리는 용도예요). 긴 방일수록 생성 입력이 길어져요.",
        "기억 기능이 전부 함께 멈춰요 — 엔딩·그림 판정 윈도우, 장면 회상·사실 주입·지식 범위 필터, 요약 접기와 그 뒤의 장면·사실 추출·인상 쓰기·임베딩 채우기. 그 스위치들이 켜져 있어도 돌지 않아요.",
      ],
      notes: ["기억 스위치를 덮어쓰면 리플레이 도구가 .env 값으로 재현해 그 턴과 어긋나요."],
    },
  },
  memory_window_ending_judgment: {
    on: {
      changes: ["엔딩 판정에 대화 전체 대신 요약과 최근 원문을 실어요."],
      warnings: [inertWhenOff("memory_window_generation")],
    },
    off: {
      changes: [
        "판정이 대화 전체를 실어 긴 방에서 토큰 원가·지연이 턴 수만큼 늘고 판정 시간 상한·컨텍스트 한도에 닿을 수 있어요.",
      ],
    },
  },
  memory_window_image_judgment: {
    on: {
      changes: ["상황 이미지·미디어 북 칸 판정에 최근 원문만 실어요."],
      warnings: [inertWhenOff("memory_window_generation")],
    },
    off: {
      changes: [
        "그림 판정 입력이 길어져 원가·지연이 늘어요 — 미디어 북 칸 판정은 엔딩 뒤·재생성까지 매 턴 돌아 끄면 가장 크게 늘어요.",
      ],
    },
  },
  memory_episodes_recall: {
    on: {
      changes: ["매 턴 이어질 장면 기억을 생성 프롬프트에 실어요."],
      warnings: [
        inertWhenOff("memory_window_generation"),
        (context) => (context.isOn("memory_episodes_extract") ? null : "장면 추출이 꺼져 있어 새 장면이 생기지 않아요."),
      ],
    },
    off: { changes: ["다음 턴부터 생성 프롬프트에 장면 기억을 싣지 않아요."] },
  },
  memory_facts_inject: {
    on: {
      changes: ["매 턴 관계·사실 기억을 생성 프롬프트에 실어요."],
      warnings: [
        inertWhenOff("memory_window_generation"),
        (context) => (context.isOn("memory_facts_extract") ? null : "사실 추출이 꺼져 있어 새 사실이 생기지 않아요."),
        (context) =>
          context.isOn("memory_embed_write") && context.isOn("memory_embed_recall")
            ? null
            : "운영 순서는 임베딩 쓰기·읽기를 켠 뒤 마지막에 켜는 거예요.",
      ],
    },
    off: { changes: ["다음 턴부터 생성 프롬프트에 사실 기억을 싣지 않아요."] },
  },
  memory_knowledge_filter: {
    on: {
      changes: ["이번 장면에 없는 인물만 아는 비밀을 사실 섹션에서 빼요."],
      notes: ["요약 비밀 표기와 한 번에 켜요."],
      warnings: [
        (context) => {
          if (!context.isOn("memory_window_generation")) return inertWhenOffText("memory_window_generation");
          if (!context.isOn("memory_episodes_recall") && !context.isOn("memory_facts_inject")) {
            return "장면 회상과 사실 주입이 모두 꺼져 있어 켜도 돌지 않아요 — 실효 값만 켜짐으로 바뀌어요.";
          }
          return null;
        },
      ],
    },
    off: {
      changes: ["사실 섹션에서 장면에 없는 인물만 아는 비밀을 거르지 않아요."],
      warnings: [
        (context) =>
          context.isOn("memory_facts_inject")
            ? "사실 주입이 켜진 동안 먼저 끄지 않아요 — 처리방침의 \"비밀을 아는 인물이 장면에 없으면 보내지 않는다\"가 사실 쪽에서는 이 필터가 켜져 있을 때만 참이에요. 사실 주입부터 끄세요."
            : null,
      ],
    },
  },
  memory_summary_secret_marking: {
    on: {
      changes: ["다음 접기부터 모든 방의 요약 글이 바뀌고 그 요약이 생성·엔딩 판정에도 실려요."],
      warnings: [inertWhenOff("memory_window_generation")],
    },
    off: { changes: ["다음 접기부터 비밀 표기가 빠지고, 이미 쓴 요약은 남아요."] },
  },
  memory_episodes_extract: {
    on: {
      changes: ["요약이 접은 구간을 장면 기억으로 뽑아요."],
      notes: [EXTRACT_CATCH_UP_NOTE],
      warnings: [inertWhenOff("memory_window_generation")],
    },
    off: { changes: [LEFTOVER_ROWS_LINE] },
  },
  memory_facts_extract: {
    on: {
      changes: ["요약이 접은 구간을 관계·사실 기억으로 뽑아요."],
      notes: [EXTRACT_CATCH_UP_NOTE],
      warnings: [inertWhenOff("memory_window_generation")],
    },
    off: { changes: [LEFTOVER_ROWS_LINE] },
  },
  memory_impressions_write: {
    on: {
      changes: ["접기 몇 번마다 인물 사이 감정 흐름(인상)을 쌓아요. 프롬프트에는 싣지 않아요."],
      // 묶음의 모든 스냅샷에서 두 추출이 다 끝나야 인상 묶음을 만든다 — 하나만 꺼져도 쌓이지 않는다.
      warnings: [inertWhenOff("memory_window_generation", "memory_episodes_extract", "memory_facts_extract")],
    },
    off: { changes: [LEFTOVER_ROWS_LINE] },
  },
  memory_items_visible: {
    on: {
      changes: ["방 주인에게 장면·사실 기억 목록, 잊게 하기, 요약 다시 만들기(유료)가 열려요."],
      notes: ["기억 열람·잊게 하기를 적은 처리방침 판이 게시된 뒤에만 켜요."],
    },
    off: {
      changes: [
        "다음 요청부터 그 라우트가 404 이고 웹 기억 패널은 탭 없는 예전 모양이에요. 이미 잊게 한 장면·사실은 돌아오지 않아요.",
      ],
    },
  },
  memory_impressions_visible: {
    on: {
      changes: ["기억 보기 목록에 인상 구획이 생겨요."],
      notes: ["처리방침에 인상 열람을 게시한 뒤에만 켜요."],
      warnings: [inertWhenOff("memory_items_visible")],
    },
    off: { changes: ["다음 요청부터 인상 구획이 빠지고, 쌓인 인상은 남아요."] },
  },
  stat_event_log: {
    on: { changes: ["턴 기록에 스탯 판정 규칙·폭을 남겨요."], notes: [STAT_LOG_SAME_NOTE] },
    off: { changes: ["턴 기록에 스탯 판정 규칙·폭을 더 남기지 않아요."], notes: [STAT_LOG_SAME_NOTE] },
  },
  local_image_reference_enabled: {
    on: {
      changes: ["본인이 만든 생성 이미지를 참조로 집 PC 에 실어요."],
      notes: ["집 PC 서버가 참조 필드를 모르면 참조를 조용히 무시한 채 과금돼요 — 서버 쪽 반영을 확인한 뒤 켜요."],
    },
    off: { changes: ["생성 화면에 참조 행이 안 뜨고, 참조를 실은 요청은 400 으로 거절·환불돼요."] },
  },
} satisfies Record<FeatureSwitchName, { on: DirectionCopy; off: DirectionCopy }>;

function resolveLines(lines: readonly EffectLine[] | undefined, context: EffectContext): string[] {
  return (lines ?? []).flatMap((line) => {
    const text = typeof line === "string" ? line : line(context);
    return text === null ? [] : [text];
  });
}

/** 실효 값이 `value` 로 바뀌는 저장의 결과 문장. 바꾸기와, 지워서 실효 값이 바뀌는 덮어쓰기 지우기가 같은 문장을 쓴다. */
export function resolveEffects(name: FeatureSwitchName, value: boolean, context: EffectContext): ResolvedEffects {
  const copy: DirectionCopy = SWITCH_EFFECTS[name][value ? "on" : "off"];
  return {
    changes: resolveLines(copy.changes, context),
    irreversible: resolveLines(copy.irreversible, context),
    notes: resolveLines(copy.notes, context),
    warnings: resolveLines(copy.warnings, context),
    tone: copy.tone ?? "default",
  };
}

/** 확인 모달·덮어쓰기 칸이 함께 쓰는 덮어쓰기 표기. */
export function overrideText(value: boolean | null): string {
  return value === null ? "없음" : onOffText(value);
}

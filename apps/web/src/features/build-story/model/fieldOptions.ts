import {
  type LOGIC_OPERATORS,
  MAX_KEYWORD_NOTE_STICKY_TURNS,
  type KeywordNoteValues,
  type PromptTemplate,
  type StatChangeDirection,
  type Target,
  type Visibility,
} from "./schema";

// 선택지 화면 글자를 빌더 탭과 작성 가이드의 빌더 모양 예시가 같이 읽는다. 값 목록은 스키마가 단일 소스이고, 여기서는
// 값마다 글자만 붙인다.

// 템플릿마다 실제로 다른 지시문(생성 프롬프트 variant)을
// 가지므로, 여기 설명이 빈말이 아니다. 안내문이라 지시문을 그대로 옮기지 않고 창작자가 읽을 말로 풀었다.
export const PROMPT_TEMPLATE_LABELS: Record<PromptTemplate, { label: string; description: string }> = {
  basic: {
    label: "기본",
    description: "상황을 담백하게 그리며, 매 턴 다음 장면으로 이어질 실마리를 남겨요.",
  },
  emotional: {
    label: "감정형",
    description: "인물의 감정 변화를 섬세한 단서로 드러내 사용자가 알아챌 수 있게 해요.",
  },
  simulation: {
    label: "시뮬레이션형",
    description: "매 턴 무엇이 달라졌는지, 지금 무엇을 조작할 수 있는지 명확히 보여줘요.",
  },
  custom: {
    label: "커스텀",
    description: "직접 작성한 프롬프트로 진행하되, 기본 템플릿과 같은 진행 방식이 바탕에 깔려요.",
  },
};

export const TARGET_LABELS: Record<Target, string> = {
  female: "여성향",
  male: "남성향",
  all: "공용",
};

export const VISIBILITY_LABELS: Record<Visibility, string> = {
  public: "전체공개",
  link: "링크공개",
  private: "비공개",
};

export const KEYWORD_NOTE_SCOPE_LABELS: Record<KeywordNoteValues["scope"]["kind"], string> = {
  global: "스토리 전체",
  startingSetup: "특정 시작설정",
};

/** 변화 방향 셀렉트 항목과 접힌 스탯 요약이 함께 쓰는 작가 말. "양방향/증가만/감소만"은 개발 용어라 쓰지 않는다. */
export const STAT_CHANGE_DIRECTION_LABELS: Record<StatChangeDirection, string> = {
  both: "오르내림",
  increase: "오르기만",
  decrease: "내리기만",
};

/** 스탯 기반 규칙 목록에서 이웃한 두 항목을 잇는 접속사. 빌더의 관계 토글과 작성 가이드의 규칙 그림이 같은 말을 쓴다. */
export const LOGIC_OPERATOR_LABELS: Record<(typeof LOGIC_OPERATORS)[number], string> = {
  and: "그리고",
  or: "또는",
};

export const STICKY_TURN_OPTIONS = Array.from({ length: MAX_KEYWORD_NOTE_STICKY_TURNS + 1 }, (_, turns) => ({
  value: String(turns),
  label: turns === 0 ? "이번 턴만" : `다음 ${turns}턴까지`,
}));

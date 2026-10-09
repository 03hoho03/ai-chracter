import type { components } from "@ai-character-chat/api-types";

/** 다른 회원이 이 작품으로 대화 소설을 만들 수 있는지에 대한 작가의 허락 단계. 작품 헤더 값이라 버전과 무관하게
 * 저장 즉시 적용된다. 작가 본인은 단계와 상관없이 만들 수 있다. */
export type NovelPermission = components["schemas"]["ContentNovelPermissionUpdateRequest"]["novelPermission"];

/** 화면에 나열하는 순서 — 막는 쪽에서 넓히는 쪽으로. 빌더 두 탭과 발행 후 설정 모달이 같은 목록을 쓴다. */
export const NOVEL_PERMISSION_VALUES = ["forbidden", "private", "public"] as const satisfies readonly NovelPermission[];

/** 새 작품의 기본값. 서버의 칸 기본값과 같아야 한다 — 어긋나면 빈 초안의 첫 자동저장이 서버 기본값을 이 값으로 덮는다. */
export const DEFAULT_NOVEL_PERMISSION: NovelPermission = "private";

export const NOVEL_PERMISSION_FIELD_LABEL = "다른 회원의 소설 만들기";

/** 단계마다 이름과 한 줄 설명. 설명은 "다른 회원이 무엇을 할 수 있는가"로 끝나는 같은 골격이라 나란히 읽으면 차이가 보인다.
 * 공개 소설 기능은 아직 없어서 마지막 단계는 값만 저장된다 — 그 사실을 설명에 적어 지금 바로 공개되는 것으로 읽히지 않게 한다. */
export const NOVEL_PERMISSION_COPY: Record<NovelPermission, { label: string; description: string }> = {
  forbidden: {
    label: "허용 안 함",
    description: "다른 회원은 이 작품의 대화로 새 소설을 만들 수 없어요. 이미 만든 소설은 그대로 남아요.",
  },
  private: {
    label: "나만 보는 소설",
    description: "다른 회원이 자기 대화를 자기만 보는 소설로 만들 수 있어요.",
  },
  public: {
    label: "공개 소설까지",
    description: "소설을 다른 사람에게 공개하는 것까지 허락해요. 공개 소설 기능이 열리면 적용돼요.",
  },
};

/** 허락한 두 단계(나만 보는 소설·공개 소설까지)에 함께 붙는 적립 안내. 비율 표기(`"5%"`)는 서버 설정값에서 온다. */
export function formatNovelPermissionEarningNote(rate: string): string {
  return `두 경우 모두 소설 생성에 쓴 유료 클로버의 ${rate}가 크리에이터 정산으로 적립돼요.`;
}

export function isNovelPermission(value: string): value is NovelPermission {
  return NOVEL_PERMISSION_VALUES.some((permission) => permission === value);
}

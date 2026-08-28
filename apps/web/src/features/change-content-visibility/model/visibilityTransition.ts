import type { ContentVisibility } from "@/entities/content";

/** 전환 메뉴에 나열하는 순서 — 노출 범위가 넓은 쪽부터. 프로필의 공개여부 필터와 같은 순서다. */
const VISIBILITY_ORDER: ContentVisibility[] = ["public", "link", "private"];

/** 공개범위 **전환** 카피. 진입점이 둘(콘텐츠 상세 "⋯" 메뉴 / 프로필 카드 "⋯" 메뉴)이라 두 메뉴가
 * 같은 라벨과 같은 문구를 쓰도록 feature의 model에 모은다. 상태 표시용 라벨(프로필 카드의 공개범위
 * 배지, 공개여부 필터)은 아직 각자 사본을 갖고 있다 — /my가 같은 배지·필터를 다시 쓰는 US-008/009에서
 * 함께 entities로 내리는 게 맞다.
 *
 * `description`은 확인 모달 본문이며 두 규칙을 따른다 — (1) 제목("…로 전환할까요?")이 이미 말한 동작을
 * 되풀이하지 않고 **결과만** 적는다(`ConfirmChatRoomActionModal` 호출부들이 쓰는 집안 문법:
 * "삭제한 이미지는 복구할 수 없어요."), (2) 세 문구가 "누가 볼 수 있는가"로 끝나는 같은 골격을 갖는다 —
 * 나란히 놓고 읽었을 때 셋의 차이가 한 눈에 보여야 한다. */
export const VISIBILITY_TRANSITION_COPY: Record<
  ContentVisibility,
  { label: string; description: string }
> = {
  public: {
    label: "공개",
    description: "홈과 검색에 노출되고, 누구나 볼 수 있어요.",
  },
  link: {
    label: "링크공개",
    description: "홈과 검색에서 빠지고, 링크를 가진 사람만 볼 수 있어요.",
  },
  private: {
    label: "비공개",
    description: "홈과 검색에서 더 이상 노출되지 않고, 나만 볼 수 있어요.",
  },
};

/** 현재 공개범위를 뺀 나머지 두 전환. 현재 상태와 같은 항목은 메뉴에 내지 않는다. */
export function listVisibilityTransitions(current: ContentVisibility): ContentVisibility[] {
  return VISIBILITY_ORDER.filter((visibility) => visibility !== current);
}

/** 이용제한 작품에서 전환 항목을 비활성으로 두는 **이유** — 숨기지 않고 메뉴 안에 그대로 적는다(US-008).
 * 숨기면 같은 메뉴가 작품마다 달라 보이는데 왜인지 알 길이 없어 작가가 버그로 읽는다.
 *
 * 문장이 "바꿀 수 없어요"가 아니라 "바꿔도 노출되지 않아요"인 이유: `PATCH /contents/{id}/visibility`는
 * 이용제한 작품에도 200을 주고 값을 실제로 바꾼다. 막는 건 서버가 아니라 **노출 쿼리**다 —
 * 홈·검색·타인 프로필이 `moderation_status == NORMAL`을 함께 걸어서(`content/router.py`의 `list_contents`)
 * 공개로 바꿔도 남들에겐 안 보인다. 비활성은 그 헛수고를 막는 FE 정책이므로 사유도 그렇게 적는다. */
export const VISIBILITY_TRANSITION_BLOCKED_REASON = "이용제한 중에는 공개범위를 바꿔도 노출되지 않아요.";

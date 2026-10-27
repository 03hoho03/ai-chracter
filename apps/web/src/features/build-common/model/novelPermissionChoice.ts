import type { NovelPermission } from "@/entities/content";

/** 두 빌더에서 소설 만들기 허락 칸의 폼 경로. 발행 전 확인 목록·첫 오류 이동이 이 경로로 그 칸을 짚는다. */
export const NOVEL_PERMISSION_PATH = "registration.novelPermission";

type ChoiceState = {
  /** 발행된 버전 수. `undefined` 는 이력을 확인하지 못한 것이다(조회 대기·실패). */
  publishedCount: number | undefined;
  /** 이 화면을 열 때 서버에 저장돼 있던 값(새 초안은 기본값). */
  savedPermission: NovelPermission;
  /** 이 화면에서 작가가 세 줄 가운데 하나를 눌렀는가. 폼 값이 아니라 화면 상태다. */
  chosen: boolean;
  /** 이 화면이 이미 고르라고 발행을 막았는가 — 발행을 누를 때 다시 읽은 이력으로 막았거나, 서버가 "먼저 고르라"는 400 으로 거절했다.
   * 그 뒤로는 화면에 붙은 이력이 무엇이든 고를 때까지 묻는다(막힘과 그림이 같은 판정이어야 고를 수 있다). */
  alreadyAsked: boolean;
};

function hasPublished(publishedCount: number | undefined): boolean {
  return publishedCount !== undefined && publishedCount > 0;
}

/**
 * 첫 발행 전에 작가에게 허락 단계를 고르라고 해야 하는가. 순수 함수.
 *
 * 칸은 서버에서 늘 값이 있고(기본값 허용 안 함), 새 초안은 첫 저장에 화면 기본값을 싣는다 — 그래서 저장된 "허용 안 함"이 고른 것인지
 * 기본값인지 서버도 화면도 모른다. 그래서 "발행 이력 없음 ∧ 저장값 허용 안 함 ∧ 이 화면에서 아직 안 고름"일 때만 묻는다. 저장값이
 * 넓힌 값(나만 보는 소설·공개 소설까지)이면 누군가 이미 고른 것이다. 다시 연 초안의 "허용 안 함"은 이미 골랐더라도 한 번 더 묻는다.
 *
 * 이력을 모르면(조회 실패) 이력 없음으로 본다 — 발행작에 한 번 더 묻는 쪽이 첫 발행을 고르지 않고 보내는 쪽보다 덜 해롭다. 이미
 * 고르라고 막았으면(서버 거절 포함 — 이 화면이 이력을 잘못 알았다) 고를 때까지 묻는다.
 */
export function needsNovelPermissionChoice({ publishedCount, savedPermission, chosen, alreadyAsked }: ChoiceState): boolean {
  if (chosen) return false;
  if (alreadyAsked) return true;
  return !hasPublished(publishedCount) && savedPermission === "forbidden";
}

/**
 * 발행 요청 본문에 실을 허락 값. 싣지 않으면 `undefined`. 순수 함수.
 *
 * 고른 경우에만 싣는다 — 폼 값은 늘 있어 그대로 실으면 고르지 않아도 서버 검사를 통과한다. 저장값이 넓힌 값인 미발행 초안은 이미 고른
 * 것이라 싣는다. 고르지 않은 발행작은 싣지 않아 지금 값을 그대로 둔다.
 */
export function novelPermissionPublishValue(
  { publishedCount, savedPermission, chosen }: Omit<ChoiceState, "alreadyAsked">,
  value: NovelPermission,
): NovelPermission | undefined {
  if (chosen) return value;
  if (!hasPublished(publishedCount) && savedPermission !== "forbidden") return value;
  return undefined;
}

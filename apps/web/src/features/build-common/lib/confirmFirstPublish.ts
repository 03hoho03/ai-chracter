import type { QueryClient } from "@tanstack/react-query";

import { contentVersionsQueryOptions, type ContentVisibility } from "@/entities/content";

import { needsFirstPublishConfirm } from "../model/firstPublish";
import { FirstPublishConfirmModal } from "../ui/FirstPublishConfirmModal";

type ConfirmFirstPublishArgs = {
  /** 빌더의 작품 id. 아직 서버에 초안이 없으면(`/new`) `undefined` — 발행 이력이 있을 수 없다. */
  contentId: string | undefined;
  contentLabel: string;
  visibility: ContentVisibility;
  visibilityLabel: string;
};

let isConfirming = false;

/**
 * 발행을 이어가도 되는가. 첫 발행이면 확인창을 띄워 답을 돌려주고, 이미 발행한 작품이면 묻지 않고 `true`.
 *
 * 발행 이력은 누를 때마다 서버에서 다시 읽는다(`fetchQuery` 는 신선하지 않은 캐시를 다시 받는다) — 다른 탭에서 방금 발행한
 * 작품을 이 탭이 첫 발행으로 착각하지 않게. 조회가 실패하면 묻는다(`needsFirstPublishConfirm`).
 *
 * 이력을 읽는 동안에는 발행 버튼이 아직 잠기지 않아 빠르게 두 번 누르면 확인창이 두 겹으로 뜬다. 진행 중인 확인이 있으면
 * 뒤의 누름은 발행하지 않고 끝낸다.
 */
export async function confirmFirstPublish(queryClient: QueryClient, args: ConfirmFirstPublishArgs): Promise<boolean> {
  if (isConfirming) return false;
  isConfirming = true;
  try {
    return await askIfFirstPublish(queryClient, args);
  } finally {
    isConfirming = false;
  }
}

async function askIfFirstPublish(
  queryClient: QueryClient,
  { contentId, contentLabel, visibility, visibilityLabel }: ConfirmFirstPublishArgs,
): Promise<boolean> {
  const publishedVersionCount =
    contentId === undefined
      ? 0
      : // 재시도하지 않는다 — 전역 기본값(5xx·네트워크 실패 3회 백오프)이면 실패 때 확인창이 몇 초 늦게 뜬다.
        await queryClient.fetchQuery({ ...contentVersionsQueryOptions(contentId), retry: false }).then(
          (versions) => versions.length,
          () => undefined,
        );
  if (!needsFirstPublishConfirm(publishedVersionCount)) return true;
  return FirstPublishConfirmModal.call({ contentLabel, visibility, visibilityLabel });
}

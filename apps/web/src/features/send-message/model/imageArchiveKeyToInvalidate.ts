import type { QueryKey } from "@tanstack/react-query";

import { characterImageArchiveKeys } from "@/entities/character-image-archive";
import type { ChatMessage } from "@/entities/chat-room";
import { storyImageArchiveKeys } from "@/entities/story-image-archive";
import { assertNever } from "@/shared/lib/assertNever";

/** 이 방의 이미지 보관함이 어느 작품의 것인가. */
export type ImageArchiveTarget = {
  contentType: "character" | "story";
  contentId: string;
};

/**
 * 턴이 끝났을 때 낡게 표시할 보관함 쿼리 키. 없으면 undefined.
 * - 캐릭터: 상황별 이미지가 붙은 응답일 때만 해금이 바뀐다.
 * - 스토리: 그림이 붙은 응답(대화 중 판정)뿐 아니라 엔딩 도달로 에필로그 속 칸도 해금되는데, 이 콜백은 엔딩 도달
 *   여부를 모른다. 관찰자가 없으면 무효화는 비용이 없으므로 매 턴 낡게 표시한다.
 */
export function imageArchiveKeyToInvalidate(
  target: ImageArchiveTarget | undefined,
  message: Pick<ChatMessage, "imageId">,
): QueryKey | undefined {
  if (target === undefined) return undefined;
  switch (target.contentType) {
    case "story":
      return storyImageArchiveKeys.list(target.contentId);
    case "character":
      return message.imageId ? characterImageArchiveKeys.list(target.contentId) : undefined;
    default:
      return assertNever(target.contentType);
  }
}

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { characterImageArchiveKeys } from "@/entities/character-image-archive/@x/session";
import { chatModelKeys } from "@/entities/chat-model/@x/session";
import { chatRoomKeys } from "@/entities/chat-room/@x/session";
import { cloverKeys } from "@/entities/clover/@x/session";
import { commentKeys } from "@/entities/comment/@x/session";
import { contentKeys, favoriteKeys } from "@/entities/content/@x/session";
import { creatorPayoutKeys } from "@/entities/creator-payout/@x/session";
import { draftKeys } from "@/entities/draft/@x/session";
import { generatedImagesKeys } from "@/entities/generated-image/@x/session";
import { imageJobKeys } from "@/entities/image-job/@x/session";
import { inquiryKeys } from "@/entities/inquiry/@x/session";
import { notificationKeys } from "@/entities/notification/@x/session";
import { novelKeys } from "@/entities/novel/@x/session";
import { personaKeys } from "@/entities/persona/@x/session";
import { previewSessionKeys } from "@/entities/preview-session/@x/session";
import { storyImageArchiveKeys } from "@/entities/story-image-archive/@x/session";
import { webnovelKeys } from "@/entities/webnovel/@x/session";

import { sessionKeys } from "../api/keys";

/** 로그인한 사람에 따라 값이 달라지는 캐시의 키 접두 — 그 사람의 것(`/me/*`·내 방·내 소설 등)이거나, 같은 주소라도
 * 보는 사람마다 응답이 다른 것(작품 상세의 좋아요·소유 여부, 노벨의 소장·읽은 자리, 허용에 따라 달라지는 채팅 모델 목록).
 * **로그인 사용자별 캐시를 새로 만들면 여기에 더한다** — 로그아웃·탈퇴·로그인이 모두 이 목록 하나로 비운다.
 *
 * 넣지 않은 것: 세션(비우는 방법이 달라 `clearViewerSession` 이 따로 다룬다), 누구에게나 같은 응답(공지·약관·장르·
 * 작품 둘러보기·홈 큐레이션·클로버 가격·댓글 스티커·프로필, 그리고 로그인이 필요하지만 응답이 계정과 무관한 이미지 모델). */
const VIEWER_QUERY_KEYS: readonly QueryKey[] = [
  chatRoomKeys.all,
  characterImageArchiveKeys.all,
  storyImageArchiveKeys.all,
  chatModelKeys.all,
  cloverKeys.balance(),
  cloverKeys.missions(),
  cloverKeys.ledgers(),
  commentKeys.all,
  contentKeys.lists(),
  contentKeys.details(),
  contentKeys.drafts(),
  contentKeys.versionLists(),
  favoriteKeys.all,
  creatorPayoutKeys.all,
  draftKeys.all,
  generatedImagesKeys.all,
  imageJobKeys.all,
  inquiryKeys.all,
  notificationKeys.all,
  novelKeys.all,
  personaKeys.all,
  previewSessionKeys.all,
  webnovelKeys.all,
];

/** 앞 계정의 사용자별 캐시를 비운다. 지킬 것은 둘이다 — 다음 계정에게 앞 계정의 값이 한 프레임도 보이지 않을 것, 이미
 * 지워진 쿠키로 요청이 나가지 않을 것.
 *
 * 화면에 붙은 캐시는 **다시 받지 않고 값만 비운다**(`query.reset()`). `resetQueries` 는 비운 뒤 화면에 붙은 쿼리를 곧바로
 * 다시 받아 401 이 나고, `removeQueries` 는 붙어 있던 관찰자가 다시 그려질 때 캐시에 새 쿼리를 만들어 조회가 켜져 있으면
 * 역시 다시 받는다(그 전까지는 지운 쿼리를 쥐고 옛 값을 그린다). 같은 쿼리를 비우기만 하면 관찰자는 그 자리에서 빈 값을
 * 그리고, 조회 조건이 바뀌지 않는 한 다시 받지 않는다. 화면에 붙지 않은 캐시는 지운다 — 다음에 여는 화면이 새로 받는다. */
export function clearViewerQueries(queryClient: QueryClient): void {
  const queryCache = queryClient.getQueryCache();
  for (const queryKey of VIEWER_QUERY_KEYS) {
    for (const query of queryCache.findAll({ queryKey })) {
      if (query.getObserversCount() > 0) query.reset();
      else queryCache.remove(query);
    }
  }
}

/** 로그아웃·탈퇴 뒤 정리. 사용자별 캐시를 비우고 세션을 비로그인으로 되돌린다. */
export function clearViewerSession(queryClient: QueryClient): void {
  clearViewerQueries(queryClient);
  // 세션만은 `resetQueries` 다. invalidateQueries only marks the query stale and refetches in the background — until
  // that refetch resolves, `data` keeps the previous (logged-in) value, so the header wouldn't switch to the logged-out
  // UI immediately. setQueryData(key, undefined) is a documented no-op (TanStack Query skips the update whenever the new
  // value resolves to undefined). resetQueries clears `state.data` on the live Query object and synchronously notifies
  // observers, so every mounted `useSessionQuery()` re-renders as logged-out right away. 이 리셋이 부르는 `GET /me` 는
  // 401 로 끝난다. 그 401 을 없애려고 다시 받지 않는 리셋(`query.reset()`)을 쓰면 세션이 pending 에 머물러, 세션의
  // `isPending` 으로 비로그인을 가리는 좌측 패널·드로어의 최근 대화(`RecentChatsSection`)가 비로그인 안내 대신 로딩에 남는다.
  void queryClient.resetQueries({ queryKey: sessionKeys.current() });
}

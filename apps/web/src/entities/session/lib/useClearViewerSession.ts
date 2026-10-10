import { useQueryClient } from "@tanstack/react-query";
import { useSetAtom } from "jotai";

import { commentDraftLogoutRevisionAtom } from "@/entities/comment/@x/session";

import { clearViewerSession } from "./clearViewerSession";

/** 로그아웃·탈퇴가 성공한 뒤 부를 정리 함수. 두 기능(`features/logout`·`features/withdraw-account`)이 서로 import 하지
 * 못해 정리 목록을 여기 한 곳에 둔다 — 캐시(`clearViewerSession`)와 함께, 쓰다 만 댓글 초안이 다음 계정에 남지 않게
 * 초안 리비전도 올린다. */
export function useClearViewerSession(): () => void {
  const queryClient = useQueryClient();
  const setCommentDraftLogoutRevision = useSetAtom(commentDraftLogoutRevisionAtom);
  return () => {
    setCommentDraftLogoutRevision((revision) => revision + 1);
    clearViewerSession(queryClient);
  };
}

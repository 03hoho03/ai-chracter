import { useEffect, useRef } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import type { ContentType } from "../../../entities/content";
import { useStartChatMutation } from "../../../entities/chat-room";
import { useSessionQuery } from "../../../entities/session";
import { useRawSearchParams } from "../../../shared/lib/search-params/useRawSearchParams";

interface UsePlayContentOptions {
  /** 스토리 전용 — 로그인 복귀 후 자동 재생 시 로컬 선택 state도 복원값으로 맞춘다. */
  onRestoreSetup?: (startingSetupId: string) => void;
}

/**
 * techspec-content-detail.md §3 / techspec-chat-common.md §3 — 플레이 버튼의 로그인 유도 +
 * 복귀 후 자동 시작 로직. 캐릭터/스토리 챗 모두 실제 대화방을 생성(`useStartChatMutation`)한 뒤
 * `/chat/$roomId`로 이동한다(스토리는 US-057부터 `contentType: "story"` + `startingSetupId`를 함께 보낸다).
 */
export function usePlayContent(contentId: string, contentType: ContentType, options?: UsePlayContentOptions) {
  const session = useSessionQuery();
  const navigate = useNavigate();
  const params = useRawSearchParams();
  const hasAutoStartedRef = useRef(false);
  const startChatMutation = useStartChatMutation();

  async function start(startingSetupId?: string) {
    try {
      const room = await startChatMutation.mutateAsync({ contentId, contentType, startingSetupId });
      void navigate({ to: "/chat/$roomId", params: { roomId: room.id } });
    } catch {
      toast.error("대화방을 시작하지 못했어요. 잠시 후 다시 시도해주세요.");
    }
  }

  useEffect(() => {
    if (hasAutoStartedRef.current) return;
    if (params.get("autoplay") !== "1") return;
    if (session.isPending) return; // GET /me 응답을 기다렸다가 한 번만 판단한다(로딩 중엔 항상 session.data가 없다).
    hasAutoStartedRef.current = true;
    if (!session.data) return; // 로그인 리다이렉트 복귀 경로라 이론상 항상 존재하지만 방어적으로 둔다.
    const restoredSetupId = params.get("startingSetupId") ?? undefined;
    if (restoredSetupId) options?.onRestoreSetup?.(restoredSetupId);
    void start(restoredSetupId);
  }, [session.isPending, session.data]);

  function handlePlay(startingSetupId?: string) {
    if (!session.data) {
      const query = new URLSearchParams({ autoplay: "1" });
      if (startingSetupId) query.set("startingSetupId", startingSetupId);
      void navigate({
        to: "/login",
        search: { redirect: `/content/${contentType}/${contentId}?${query.toString()}` },
      });
      return;
    }
    void start(startingSetupId);
  }

  return { handlePlay };
}

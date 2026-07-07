import { useEffect, useRef } from "react";
import { useNavigate } from "@tanstack/react-router";

import type { ContentType } from "../../../entities/content";
import { useSessionQuery } from "../../../entities/session";
import { useRawSearchParams } from "../../../shared/lib/hooks/useRawSearchParams";

interface UsePlayContentOptions {
  /** 스토리 전용 — 로그인 복귀 후 자동 재생 시 로컬 선택 state도 복원값으로 맞춘다. */
  onRestoreSetup?: (startingSetupId: string) => void;
}

/**
 * techspec-content-detail.md §3 / techspec-chat-common.md §3 — 플레이 버튼의 로그인 유도 +
 * 복귀 후 자동 시작 로직. 대화방 생성 API(US-051 캐릭터 챗/US-057 스토리 챗)가 아직 없어
 * 실제 채팅 세션을 만들 수 없다 — 그 전까지는 `/chat/$type/$id`(ComingSoonPage 스텁)로 이동하는
 * 것까지만 책임진다. 그 스토리들이 실제 방 생성 뮤테이션으로 교체할 때 `start()` 내부
 * navigate 대상만 바꾸면 된다.
 */
export function usePlayContent(contentId: string, contentType: ContentType, options?: UsePlayContentOptions) {
  const session = useSessionQuery();
  const navigate = useNavigate();
  const params = useRawSearchParams();
  const hasAutoStartedRef = useRef(false);

  function start(startingSetupId?: string) {
    void navigate({
      to: "/chat/$type/$id",
      params: { type: contentType, id: contentId },
      search: startingSetupId ? { startingSetupId } : {},
    });
  }

  useEffect(() => {
    if (hasAutoStartedRef.current) return;
    if (params.get("autoplay") !== "1") return;
    if (session.isPending) return; // GET /me 응답을 기다렸다가 한 번만 판단한다(로딩 중엔 항상 session.data가 없다).
    hasAutoStartedRef.current = true;
    if (!session.data) return; // 로그인 리다이렉트 복귀 경로라 이론상 항상 존재하지만 방어적으로 둔다.
    const restoredSetupId = params.get("startingSetupId") ?? undefined;
    if (restoredSetupId) options?.onRestoreSetup?.(restoredSetupId);
    start(restoredSetupId);
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
    start(startingSetupId);
  }

  return { handlePlay };
}

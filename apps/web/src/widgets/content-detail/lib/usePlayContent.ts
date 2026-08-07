import { useEffect, useRef } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { toast } from "sonner";

import type { ContentType } from "../../../entities/content";
import { useStartChatMutation } from "../../../entities/chat-room";
import { useSessionQuery } from "../../../entities/session";
import { useRawSearchParams } from "../../../shared/lib/search-params/useRawSearchParams";
import { contentDetailModalAtom } from "../../../shared/model/content-detail-modal";

interface UsePlayContentOptions {
  /** 스토리 전용 — 로그인 복귀 후 자동 재생 시 로컬 선택 state도 복원값으로 맞춘다. */
  onRestoreSetup?: (startingSetupId: string) => void;
}

/**
 * techspec-content-detail.md §3 / techspec-chat-common.md §3 — 플레이 버튼의 로그인 유도 +
 * 복귀 후 자동 시작 로직. 캐릭터/스토리 챗 모두 실제 대화방을 생성(`useStartChatMutation`)한 뒤
 * `/chat/$roomId`로 이동한다(스토리는 US-057부터 `contentType: "story"` + `startingSetupId`를 함께 보낸다).
 *
 * 모달 경유(`contentDetailModalAtom`이 차 있음)와 풀페이지 진입을 구분해 히스토리를 다르게 다룬다.
 * `useContentDetailModal.open()`이 라우터를 우회해 `/content/$type/$id` 엔트리를 하나 밀어 넣어두므로,
 * 모달에서 시작한 이동을 push하면 스택이 `[리스트, /content/x, /chat/roomId]`가 되어 채팅에서 뒤로가기가
 * 풀페이지 상세로 튄다. 모달 경유일 때만 `replace`로 그 엔트리를 덮어 뒤로가기가 리스트로 돌아가게 한다.
 */
export function usePlayContent(contentId: string, contentType: ContentType, options?: UsePlayContentOptions) {
  const session = useSessionQuery();
  const navigate = useNavigate();
  const params = useRawSearchParams();
  const hasAutoStartedRef = useRef(false);
  const startChatMutation = useStartChatMutation();
  const [modalState, setModalState] = useAtom(contentDetailModalAtom);
  const isFromModal = modalState !== null;

  async function start(startingSetupId?: string) {
    try {
      const room = await startChatMutation.mutateAsync({ contentId, contentType, startingSetupId });
      // 방 생성이 끝난 뒤에 닫는다 — 클릭 즉시 닫으면 생성을 기다리는 동안 아무 피드백 없이 리스트만 보인다.
      setModalState(null);
      void navigate({ to: "/chat/$roomId", params: { roomId: room.id }, replace: isFromModal });
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
      // 로그인 화면 위에 상세 모달이 남지 않게 한다. 히스토리 엔트리는 남겨둔다 —
      // 로그인 후 복귀 지점이 바로 그 `/content/...` 풀페이지라 뒤로가기가 그리 가는 편이 자연스럽다.
      setModalState(null);
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

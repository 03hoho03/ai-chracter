import { Button } from "@ai-character-chat/ui/components/button";
import { Globe, Loader2 } from "lucide-react";
import { useEffect } from "react";
import { toast } from "sonner";

import { toPublishFailureMessage } from "../model/publishFailure";
import { toPublicationView, toRejectionNotice } from "../model/publicationView";
import { useNovelPublishActions } from "../model/useNovelPublishActions";
import { PublishNovelModal } from "./PublishNovelModal";
import { WithdrawNovelPublicationModal } from "./WithdrawNovelPublicationModal";

type PublishableNovel = { id: string; chapters: readonly { id: string; ordinal: number }[] };

/** 편집 보드 상단 바의 "노벨 공개" — 작품 정보의 공개 절과 같은 공개 모달을 연다. 공개할 것이 있을 때만(공개 전,
 * 거둔 공개를 다시 열 수 있을 때, 공개 중인데 새 화·고친 내용이 있을 때) 보인다 — 상태 안내와 거두기는 작품 정보가
 * 맡는다. 확인하는 동안은 아이콘이 스피너로 바뀌고 접근 이름이 진행을 말한다. 결과는 토스트로 알린다(보드에는 공개
 * 절이 없다). `sm` 미만은 아이콘만 남긴다(빌더 상단 바와 같은 규칙). */
export function NovelPublishBoardButton({ novel }: { novel: PublishableNovel }) {
  const actions = useNovelPublishActions(novel);
  const status = actions.publication.data;
  const runState = actions.runState;
  const failure = runState.kind === "failed" ? runState.failure : undefined;

  // 실패는 한 번만 알린다(같은 실패 객체로 다시 그려질 때 또 띄우지 않는다).
  useEffect(() => {
    if (failure === undefined) return;
    const message = toPublishFailureMessage(failure);
    if (message !== undefined) toast.error(message);
  }, [failure]);

  // 거절은 다시 받은 공개 상태가 어느 화의 어느 글인지 말한다 — 그 상태가 도착했을 때 알린다.
  // 다시 받을 때마다 객체가 바뀌므로 심사 시각으로 한 번만 띄운다.
  const rejection = failure?.kind === "rejected" && status?.lastScreening?.outcome === "rejected" ? status.lastScreening : undefined;
  const rejectionMessage = rejection === undefined ? undefined : toRejectionNotice(rejection).message;
  const rejectionAt = rejection?.createdAt;
  useEffect(() => {
    if (rejectionAt === undefined || rejectionMessage === undefined) return;
    toast.error(rejectionMessage, { id: `novel-publish-rejected-${rejectionAt}` });
  }, [rejectionAt, rejectionMessage]);

  if (status === undefined) return null;
  const view = toPublicationView(status);
  const isChecking = runState.kind === "checking";
  const canPublish =
    view.kind === "unpublished" ||
    (view.kind === "withdrawn" && view.canReopen) ||
    (view.kind === "public" && view.canRepublish);
  if (!canPublish && !isChecking) return null;

  const label = isChecking ? `노벨 공개 확인 중 ${runState.current}/${runState.total}` : "노벨 공개";

  return (
    <>
      <PublishNovelModal />
      <WithdrawNovelPublicationModal />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label={label}
        aria-disabled={isChecking}
        className="aria-disabled:opacity-65"
        onClick={() => {
          if (isChecking) return;
          actions.clearFailure();
          void actions.openPublish(status).then((isDone) => {
            if (isDone) toast.success("노벨에 공개했어요.");
          });
        }}
      >
        {/* 진행 표시라 동작 줄이기 설정에서도 돈다. */}
        {isChecking ? <Loader2 aria-hidden className="animate-spin" /> : <Globe aria-hidden />}
        <span className="hidden sm:inline">{isChecking ? `확인 중 ${runState.current}/${runState.total}` : "노벨 공개"}</span>
      </Button>
    </>
  );
}

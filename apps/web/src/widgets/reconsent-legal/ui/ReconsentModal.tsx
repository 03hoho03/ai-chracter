import { useState } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  LEGAL_DOCUMENT_KINDS,
  LEGAL_DOCUMENT_LABEL,
  type LegalDocumentKind,
  type LegalDocumentResponse,
  useLegalConsentMutation,
  useLegalDocumentQuery,
} from "@/entities/legal";
import { sessionKeys, useSessionQuery } from "@/entities/session";
import { WithdrawAccountDialog } from "@/features/withdraw-account";

/** consent-gate-goal-prompt.md CG-1 — 이 모달은 닫을 수 없다. "나중에"(이전 주석이 인용하던
 * "확정 결정 D-16")를 없애고, X 버튼(`showCloseButton={false}`)·ESC·바깥 클릭을 전부 막는다.
 * D-16 원문은 저장소 전수 조사로도 추적 불가능해 새 근거로 대체한다(§2-6). 출구는 동의 또는
 * 탈퇴(CG-2) 둘뿐이라 `isDismissed`/`handleOpenChange`(`onOpenChange(false)` 경로) 자체가
 * 사라진다 — 열림 여부는 세션의 재동의 플래그로만 정해진다. */
export function ReconsentModal() {
  const sessionQuery = useSessionQuery();
  const queryClient = useQueryClient();
  const consentMutation = useLegalConsentMutation();
  const [isConsenting, setIsConsenting] = useState(false);
  // legal-revision-goal-prompt.md LR-3 — 처리방침 재동의는 kind 하나(privacy)지만 개인정보보호법
  // 제22조 제1항 제3호에 따라 수집·이용과 국외이전을 구분해 각각 체크받는다. API 호출은 그대로
  // kind="privacy" 한 번이다(서버가 privacy·transfer 두 쌍을 함께 갱신, S4에서 구현됨) — 이
  // 체크박스는 순수 FE 게이트다.
  const [isPrivacyCollectionChecked, setIsPrivacyCollectionChecked] = useState(false);
  const [isTransferChecked, setIsTransferChecked] = useState(false);

  const session = sessionQuery.data;
  const pendingKinds = LEGAL_DOCUMENT_KINDS.filter(
    (kind) =>
      (kind === "terms" && session?.termsReconsentRequired) ||
      (kind === "privacy" && session?.privacyReconsentRequired),
  );

  // 두 훅 다 무조건 호출한다(Rules of Hooks) — `enabled`로 실제 조회 여부만 가른다.
  const termsDocQuery = useLegalDocumentQuery("terms", pendingKinds.includes("terms"));
  const privacyDocQuery = useLegalDocumentQuery("privacy", pendingKinds.includes("privacy"));
  const docQueryByKind: Record<LegalDocumentKind, typeof termsDocQuery> = {
    terms: termsDocQuery,
    privacy: privacyDocQuery,
  };

  const isOpen = pendingKinds.length > 0;
  // 동의 가능 여부는 `data` 유무로만 정의한다(최초 로딩·재시도 backoff·최종 실패 전부 미보유로
  // 취급) — isPending 기반 집계는 재시도 backoff 구간(isPending && failureCount>0)을 "로딩 아님"으로
  // 잘못 읽어 handleConsent의 동기 throw 경로를 열어버렸다. 문서별 로딩·에러 UI는
  // ReconsentDocumentBody가 각자의 docQuery.isPending/isError로 그대로 그린다.
  const allDocsLoaded = pendingKinds.every((kind) => docQueryByKind[kind].data !== undefined);
  // 🔴 legal-revision-goal-prompt.md LR-3 — privacy가 pending일 때 두 체크박스를 반영하지 않으면
  // 국외이전 미체크 상태로 동의 버튼이 눌린다(§2-1이 지적한 위반을 UI가 재생산한다).
  const isPrivacyConsentReady =
    !pendingKinds.includes("privacy") || (isPrivacyCollectionChecked && isTransferChecked);
  const canConsent = allDocsLoaded && !isConsenting && isPrivacyConsentReady;

  function handleConsentClick() {
    if (!canConsent) return;
    void handleConsent();
  }

  async function handleConsent() {
    setIsConsenting(true);
    try {
      await Promise.all(
        pendingKinds.map((kind) => {
          const version = docQueryByKind[kind].data?.version;
          // allDocsLoaded가 버튼을 게이트하므로 handleConsent 호출 시점엔 모든 pendingKinds가
          // data를 갖고 있음이 보장돼 이 분기는 도달 불가능하다 — 타입만 optional이라 남겨둔다.
          if (version === undefined) throw new Error(`${kind} 문서를 아직 불러오지 못했어요`);
          return consentMutation.mutateAsync({ kind, version });
        }),
      );
      void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    } catch {
      toast.error("동의 처리에 실패했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsConsenting(false);
    }
  }

  return (
    <Dialog open={isOpen}>
      {/* 제목과 동의 버튼은 항상 보여야 하므로(약관 전문이 합쳐 약 1만 8천 자라 다이얼로그 전체를
          스크롤하면 동의 버튼이 화면 밖으로 밀린다), DialogContent를 3행 그리드(헤더/본문/푸터)로
          바꾸고 본문 행만 `minmax(0,1fr)` + `overflow-y-auto`로 스크롤시킨다. */}
      {/* consent-gate-goal-prompt.md CG-1 — X 버튼을 없애고(showCloseButton) ESC·바깥 클릭을
          preventDefault로 막는다. `...props`가 DialogPrimitive.Content로 spread되는 것을 그대로
          쓴다(packages/ui는 건드리지 않는다). */}
      <DialogContent
        showCloseButton={false}
        onEscapeKeyDown={(event) => event.preventDefault()}
        onPointerDownOutside={(event) => event.preventDefault()}
        className="grid max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] sm:max-w-lg"
      >
        <DialogHeader>
          <DialogTitle>
            {pendingKinds.map((kind) => LEGAL_DOCUMENT_LABEL[kind]).join(" · ")} 개정 안내
          </DialogTitle>
          <DialogDescription>
            동의하거나 탈퇴하기 전까지 이 안내는 닫히지 않아요. 아래 개정 내용을 확인하고
            동의해주세요.
          </DialogDescription>
        </DialogHeader>

        {/* 위쪽 테두리로 스크롤 영역의 경계를 긋는다(아래쪽은 DialogFooter의 기존 border-t가
            맡는다) — 커스텀 스크롤바 없이도 "여기부터 스크롤된다"가 읽히게. */}
        <div className="flex min-h-0 flex-col gap-6 overflow-y-auto border-t border-border pt-4">
          {pendingKinds.map((kind) => (
            <section key={kind} className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-foreground">{LEGAL_DOCUMENT_LABEL[kind]}</h3>
              <ReconsentDocumentBody docQuery={docQueryByKind[kind]} />
              {kind === "privacy" && (
                <div className="flex flex-col gap-2 border-t border-border pt-2">
                  <label className="flex items-center gap-2 text-sm text-foreground">
                    <Checkbox
                      checked={isPrivacyCollectionChecked}
                      onCheckedChange={(checked) => setIsPrivacyCollectionChecked(checked === true)}
                    />
                    (필수) 개인정보 수집·이용 동의
                  </label>
                  <label className="flex items-center gap-2 text-sm text-foreground">
                    <Checkbox
                      checked={isTransferChecked}
                      onCheckedChange={(checked) => setIsTransferChecked(checked === true)}
                    />
                    (필수) 개인정보 국외이전 동의
                  </label>
                </div>
              )}
            </section>
          ))}
        </div>

        <DialogFooter>
          {/* consent-gate-goal-prompt.md CG-2·CG-11 — 미동의 이용자의 출구는 탈퇴다. 기존
              WithdrawAccountDialog(트리거+AlertDialog+뮤테이션)를 그대로 재사용한다. */}
          <WithdrawAccountDialog label="동의하지 않고 탈퇴" />
          {/* consent-gate-goal-prompt.md CG-13 — 로딩 중 plain `disabled`는 브라우저가 즉시 blur해
              포커스를 <body>로 떨어뜨린다(apps/web/CLAUDE.md). CG-1이 ESC를 막아 키보드 복귀 수단이
              Tab 하나뿐이라 영향이 커진다. `aria-disabled` + 핸들러 early return으로 바꾼다
              (ContentListLoadMore 선례와 동일한 처방: pointer-events-none + opacity-65). */}
          <Button
            type="button"
            aria-disabled={!canConsent}
            className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
            onClick={handleConsentClick}
          >
            {isConsenting ? "처리 중..." : "동의"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type ReconsentDocumentBodyProps = {
  docQuery: UseQueryResult<LegalDocumentResponse, ApiError>;
};

/** 문서 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ReconsentDocumentBody({ docQuery }: ReconsentDocumentBodyProps) {
  if (docQuery.isPending) {
    return (
      <div className="flex flex-col gap-2">
        <div className="h-4 w-full animate-pulse rounded bg-secondary" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-secondary" />
      </div>
    );
  }

  if (docQuery.isError) {
    return <p className="text-sm text-destructive-text">불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  return <Markdown content={docQuery.data.bodyMarkdown} />;
}

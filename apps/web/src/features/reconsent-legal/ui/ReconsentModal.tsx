import { useState } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
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

/** 확정 결정 D-16 — 닫아도 "닫음" 상태를 저장하지 않는다. `isDismissed`는 이 컴포넌트가 살아 있는
 * 동안(새로고침 전까지)만 유지되는 로컬 state라 새로고침·재접속에는 세션이 여전히 재동의를
 * 요구하는 한 다시 뜬다. 동의에 성공하면 세션 쿼리를 무효화해 서버 상태로 닫는다. */
export function ReconsentModal() {
  const sessionQuery = useSessionQuery();
  const queryClient = useQueryClient();
  const consentMutation = useLegalConsentMutation();
  const [isDismissed, setIsDismissed] = useState(false);
  const [isConsenting, setIsConsenting] = useState(false);

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

  const isOpen = !isDismissed && pendingKinds.length > 0;
  const isLoadingDocs = pendingKinds.some((kind) => docQueryByKind[kind].isPending);
  const hasDocError = pendingKinds.some((kind) => docQueryByKind[kind].isError);

  function handleOpenChange(next: boolean) {
    if (!next) setIsDismissed(true);
  }

  async function handleConsent() {
    setIsConsenting(true);
    try {
      await Promise.all(
        pendingKinds.map((kind) => {
          const version = docQueryByKind[kind].data?.version;
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
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {pendingKinds.map((kind) => LEGAL_DOCUMENT_LABEL[kind]).join(" · ")} 개정 안내
          </DialogTitle>
          <DialogDescription>
            서비스를 계속 이용하려면 개정된 내용을 확인하고 동의해주세요.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-6">
          {pendingKinds.map((kind) => (
            <section key={kind} className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-foreground">{LEGAL_DOCUMENT_LABEL[kind]}</h3>
              <ReconsentDocumentBody docQuery={docQueryByKind[kind]} />
            </section>
          ))}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setIsDismissed(true)}>
            나중에
          </Button>
          <Button
            type="button"
            disabled={isLoadingDocs || hasDocError || isConsenting}
            onClick={() => void handleConsent()}
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
        <div className="h-4 w-full animate-pulse rounded bg-muted" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
      </div>
    );
  }

  if (docQuery.isError) {
    return <p className="text-sm text-destructive-text">불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  return <Markdown content={docQuery.data.bodyMarkdown} />;
}

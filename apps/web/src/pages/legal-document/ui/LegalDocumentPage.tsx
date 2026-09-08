import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { FileQuestion } from "lucide-react";

import { LEGAL_DOCUMENT_LABEL, type LegalDocumentKind, useLegalDocumentQuery } from "@/entities/legal";
import { formatDate } from "@/shared/lib/time/formatDate";

/** `/terms`·`/privacy` 공용 페이지 — 두 라우트가 `kind`만 다를 뿐 조회·렌더 로직이 완전히 같아
 * 페이지를 하나로 두고 라우트 파일에서 kind만 주입한다(routes/terms.tsx, routes/privacy.tsx). */
export function LegalDocumentPage({ kind }: { kind: LegalDocumentKind }) {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">{LEGAL_DOCUMENT_LABEL[kind]}</h1>
      <LegalDocumentBody kind={kind} />
    </main>
  );
}

type LegalDocumentBodyProps = {
  kind: LegalDocumentKind;
};

/** 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function LegalDocumentBody({ kind }: LegalDocumentBodyProps) {
  const documentQuery = useLegalDocumentQuery(kind);

  if (documentQuery.isPending) {
    return <LegalDocumentSkeleton />;
  }

  if (documentQuery.isError) {
    if (documentQuery.error.status === 404) {
      return (
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <FileQuestion aria-hidden className="size-8 text-muted-foreground" />
          <p className="text-base font-semibold text-foreground">아직 게시된 문서가 없어요</p>
          <p className="text-sm text-muted-foreground">잠시 후 다시 확인해주세요.</p>
        </div>
      );
    }

    return (
      <p className="text-sm text-destructive-text">
        {LEGAL_DOCUMENT_LABEL[kind]}을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  return (
    <>
      <p className="text-xs text-muted-foreground">
        최종 개정일 {formatDate(documentQuery.data.publishedAt)}
      </p>
      <Markdown content={documentQuery.data.bodyMarkdown} />
    </>
  );
}

function LegalDocumentSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
    </div>
  );
}

import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import type { UseQueryResult } from "@tanstack/react-query";
import { toast } from "sonner";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { LEGAL_KIND_LABELS, type LegalKind } from "../model/legalKind";
import type { AdminLegalDocumentResponse } from "../api/useLegalDocumentQuery";
import { useSaveDraftMutation } from "../api/useSaveDraftMutation";
import { useVersionsQuery } from "../api/useVersionsQuery";
import { PublishDialog } from "./PublishDialog";

type LegalEditorProps = {
  kind: LegalKind;
  documentQuery: UseQueryResult<AdminLegalDocumentResponse, ApiError>;
  draftBody: string;
  onDraftBodyChange: (next: string) => void;
};

/** 편집(좌)/미리보기(우)를 나란히 둔다 — 약관 본문이 6천~1만2천 자라 탭 전환보다 동시에
 * 비교하는 편이 낫고, 각 패널은 `max-h`로 캡을 씌워 스크롤한다(안 그러면 Textarea의
 * `field-sizing-content`가 본문 길이만큼 그대로 늘어나 페이지가 지나치게 길어진다).
 *
 * 게시 버튼은 "저장된 초안이 있고, 지금 버퍼가 그 초안과 같을 때"만 활성화한다 — 게시는
 * 서버에 저장된 초안을 발행하지 화면의 버퍼를 발행하지 않으므로, 저장 전에 게시를 누르면
 * 방금 타이핑한 내용이 아니라 이전 저장분이 나간다. 이 간극을 버튼 disabled로 막는다. */
export function LegalEditor({ kind, documentQuery, draftBody, onDraftBodyChange }: LegalEditorProps) {
  const saveDraftMutation = useSaveDraftMutation(kind);

  if (documentQuery.isPending) {
    return <div className="h-96 animate-pulse rounded-xl bg-muted" />;
  }

  if (documentQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        {LEGAL_KIND_LABELS[kind]}을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const document = documentQuery.data;
  const savedDraftBody = document.draft?.bodyMarkdown ?? "";
  const hasUnsavedChanges = draftBody !== savedDraftBody;
  const canPublish = document.draft !== null && !hasUnsavedChanges;

  let publishDisabledReason: string | undefined;
  if (document.draft === null) {
    publishDisabledReason = "초안을 먼저 작성하고 저장하세요.";
  } else if (hasUnsavedChanges) {
    publishDisabledReason = "저장하지 않은 변경사항이 있어요. 먼저 저장하세요.";
  }

  const handleSave = async () => {
    try {
      await saveDraftMutation.mutateAsync({ bodyMarkdown: draftBody });
      toast.success("초안을 저장했어요.");
    } catch {
      toast.error("저장에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-1 rounded-xl border border-border bg-card p-6">
        <h2 className="text-sm font-medium text-muted-foreground">현재 게시본</h2>
        {document.published ? (
          <p className="text-sm text-foreground">
            <span className="font-semibold">v{document.published.version}</span>
            {" · "}
            {formatDateTime(document.published.publishedAt)} 게시
            {document.published.requiresReconsent && " · 재동의 필요"}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">아직 게시된 문서가 없어요.</p>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-foreground">초안</h2>
          {hasUnsavedChanges && (
            <span className="text-xs font-medium text-muted-foreground">저장하지 않은 변경사항이 있어요</span>
          )}
        </div>

        {document.draft === null && (
          <p className="text-sm text-muted-foreground">
            아직 저장된 초안이 없어요. 내용을 작성하고 저장하면 초안이 만들어져요.
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Textarea
            value={draftBody}
            onChange={(event) => onDraftBodyChange(event.target.value)}
            placeholder="마크다운으로 본문을 작성하세요."
            aria-label={`${LEGAL_KIND_LABELS[kind]} 초안 편집`}
            className="max-h-128 min-h-128 resize-none overflow-y-auto"
          />
          <div className="max-h-128 overflow-y-auto rounded-lg border border-border bg-card p-4">
            {draftBody.trim() ? (
              <Markdown content={draftBody} />
            ) : (
              <p className="text-sm text-muted-foreground">미리볼 내용이 없어요.</p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            disabled={!hasUnsavedChanges || saveDraftMutation.isPending}
            onClick={() => void handleSave()}
          >
            {saveDraftMutation.isPending ? "저장 중..." : "초안 저장"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!canPublish}
            onClick={() => void PublishDialog.call({ kind })}
          >
            게시
          </Button>
          {publishDisabledReason && (
            <span className="text-xs text-muted-foreground">{publishDisabledReason}</span>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">게시 이력</h2>
        <VersionHistory kind={kind} />
      </section>
    </div>
  );
}

type VersionHistoryProps = {
  kind: LegalKind;
};

/** 섹션 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function VersionHistory({ kind }: VersionHistoryProps) {
  const versionsQuery = useVersionsQuery(kind);

  if (versionsQuery.isPending) {
    return <div className="h-32 animate-pulse rounded-lg bg-muted" />;
  }

  if (versionsQuery.isError) {
    return <p className="text-sm text-destructive-text">게시 이력을 불러오지 못했어요.</p>;
  }

  if (versionsQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">게시 이력이 없어요.</p>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>버전</TableHead>
            <TableHead>게시일</TableHead>
            <TableHead>재동의 필요</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {versionsQuery.data.items.map((item) => (
            <TableRow key={item.version}>
              <TableCell>{item.version}</TableCell>
              <TableCell>{formatDateTime(item.publishedAt)}</TableCell>
              <TableCell>{item.requiresReconsent ? "예" : "아니오"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

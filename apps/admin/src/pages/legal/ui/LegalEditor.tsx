import type { ApiError, components } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import type { UseQueryResult } from "@tanstack/react-query";
import { toast } from "sonner";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { RESTING_DISABLED_PRIMARY_CLASS } from "@/shared/ui/restingDisabledPrimaryClass";

import { changeNoticeToServer, type DraftBuffer, isDraftBufferDirty, toDraftBuffer } from "../model/draftBuffer";
import { toKstDate } from "../model/effectiveDate";
import { formatReconsentScopes, LEGAL_KIND_LABELS, type LegalKind } from "../model/legalKind";
import type { AdminLegalDocumentResponse } from "../api/useLegalDocumentQuery";
import { useSaveDraftMutation } from "../api/useSaveDraftMutation";
import { useVersionsQuery } from "../api/useVersionsQuery";
import { MarkdownEditPane } from "./MarkdownEditPane";
import { PublishDialog } from "./PublishDialog";
import { WithdrawDialog } from "./WithdrawDialog";

type AdminLegalPublishedItem = components["schemas"]["AdminLegalPublishedItem"];
type AdminLegalVersionState = components["schemas"]["AdminLegalVersionItem"]["state"];

const VERSION_STATE_LABELS: Record<AdminLegalVersionState, string> = {
  current: "현행",
  scheduled: "예정",
  withdrawn: "철회",
  past: "지난 판",
};

type LegalEditorProps = {
  kind: LegalKind;
  documentQuery: UseQueryResult<AdminLegalDocumentResponse, ApiError>;
  buffer: DraftBuffer;
  onBufferChange: (patch: Partial<DraftBuffer>) => void;
  /** 게시가 끝났을 때. 서버가 초안의 변경 안내를 비우므로 연 쪽이 이 문서의 편집 버퍼를 서버 값으로 되돌린다. */
  onPublished: () => void;
};

/** 본문과 변경 안내를 같은 화면에서 나란히 쓴다 — 안내는 본문에서 무엇이 바뀌었는지를 회원에게 먼저 보여 주는 요약이라,
 * 따로 쓰면 둘이 어긋나기 쉽다. 둘은 한 번에 저장된다.
 *
 * 게시 버튼은 "저장된 초안이 있고, 지금 본문·안내가 그 초안과 같을 때"만 활성화한다 — 게시는 서버에 저장된 초안을 발행하지
 * 화면의 버퍼를 발행하지 않으므로, 저장 전에 게시를 누르면 방금 타이핑한 내용이 아니라 이전 저장분이 나간다. 이 간극을 버튼
 * disabled로 막는다. */
export function LegalEditor({ kind, documentQuery, buffer, onBufferChange, onPublished }: LegalEditorProps) {
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
  const hasUnsavedChanges = isDraftBufferDirty(buffer, toDraftBuffer(document.draft));
  const canPublish = document.draft !== null && !hasUnsavedChanges;
  const hasSavedNotice = changeNoticeToServer(document.draft?.changeNoticeMarkdown ?? "") !== null;

  let publishDisabledReason: string | undefined;
  if (document.draft === null) {
    publishDisabledReason = "초안을 먼저 작성하고 저장하세요.";
  } else if (hasUnsavedChanges) {
    publishDisabledReason = "저장하지 않은 변경사항이 있어요. 먼저 저장하세요.";
  }

  const handleSave = async () => {
    try {
      // 안내는 늘 함께 보낸다 — 칸을 빼면 서버가 "그대로 두기"로 읽어 지운 안내가 되살아난다.
      await saveDraftMutation.mutateAsync({
        bodyMarkdown: buffer.bodyMarkdown,
        changeNoticeMarkdown: changeNoticeToServer(buffer.changeNotice),
      });
      toast.success("초안을 저장했어요.");
    } catch {
      toast.error("저장에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  const handlePublish = async () => {
    const isPublished = await PublishDialog.call({ kind, hasSavedNotice });
    if (isPublished) onPublished();
  };

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-sm font-medium text-muted-foreground">현재 게시본</h2>
        <dl className="flex flex-col gap-3 text-sm">
          <div className="flex flex-col gap-1">
            <dt className="text-xs font-medium text-muted-foreground">현행</dt>
            <dd className="text-foreground">
              {document.published ? (
                <PublishedSummary item={document.published} effectiveLabel="시행" />
              ) : (
                <span className="text-muted-foreground">아직 시행 중인 판이 없어요.</span>
              )}
            </dd>
          </div>
          {document.upcoming && (
            <div className="flex flex-col gap-1">
              <dt className="text-xs font-medium text-muted-foreground">시행 예정</dt>
              <dd className="flex flex-col gap-1 text-foreground">
                <PublishedSummary item={document.upcoming} effectiveLabel="시행 예정" />
                <span className="text-xs break-keep text-muted-foreground">
                  예정 판이 있는 동안은 이 문서의 다른 판을 게시할 수 없어요. 고치려면 아래 게시 이력에서 이 판을 철회한 뒤
                  다시 게시하세요.
                </span>
              </dd>
            </div>
          )}
        </dl>
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

        <MarkdownEditPane
          value={buffer.bodyMarkdown}
          onChange={(next) => onBufferChange({ bodyMarkdown: next })}
          label={`${LEGAL_KIND_LABELS[kind]} 초안 편집`}
          placeholder="마크다운으로 본문을 작성하세요."
          height="tall"
        />

        <div className="mt-3 flex flex-col gap-1">
          <h3 className="text-base font-semibold text-foreground">변경 안내</h3>
          <p className="text-xs break-keep text-muted-foreground">
            회원에게 전문보다 먼저 보이는 "무엇이 바뀌었는지" 요약이에요. 재동의를 받는 판은 안내가 있어야 게시할 수 있어요.
            게시하면 초안의 안내는 그 판으로 옮겨지고 비워져요.
          </p>
        </div>
        <MarkdownEditPane
          value={buffer.changeNotice}
          onChange={(next) => onBufferChange({ changeNotice: next })}
          label={`${LEGAL_KIND_LABELS[kind]} 변경 안내 편집`}
          placeholder="마크다운으로 이번 판의 변경 내용을 작성하세요."
          height="short"
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            className={RESTING_DISABLED_PRIMARY_CLASS}
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
            onClick={() => void handlePublish()}
          >
            게시
          </Button>
          {publishDisabledReason !== undefined && (
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

type PublishedSummaryProps = {
  item: AdminLegalPublishedItem;
  effectiveLabel: string;
};

function PublishedSummary({ item, effectiveLabel }: PublishedSummaryProps) {
  return (
    <span className="break-keep">
      <span className="font-semibold">v{item.version}</span>
      {" · "}
      {toKstDate(item.effectiveAt)} {effectiveLabel}
      {" · "}
      재동의: {formatReconsentScopes(item.reconsentScopes)}
    </span>
  );
}

type VersionHistoryProps = {
  kind: LegalKind;
};

/** 섹션 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. 시행일은 한국 날짜로 보인다 — 예약 시행은 한국
 * 시각 0시라 브라우저 시간대로 보이면 KST 밖에서 하루 앞 날짜가 된다. */
function VersionHistory({ kind }: VersionHistoryProps) {
  const versionsQuery = useVersionsQuery(kind);

  if (versionsQuery.isPending) {
    return <div className="h-32 animate-pulse rounded-lg bg-secondary" />;
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
            <TableHead>시행일(한국)</TableHead>
            <TableHead>게시일</TableHead>
            <TableHead>상태</TableHead>
            <TableHead>재동의 범위</TableHead>
            <TableHead>변경 안내</TableHead>
            <TableHead>
              <span className="sr-only">조치</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {versionsQuery.data.items.map((item) => (
            <TableRow key={item.version}>
              <TableCell className="font-medium">{item.version}</TableCell>
              <TableCell>{toKstDate(item.effectiveAt)}</TableCell>
              <TableCell>{formatDateTime(item.publishedAt)}</TableCell>
              <TableCell className={item.state === "current" || item.state === "scheduled" ? "font-semibold" : undefined}>
                {VERSION_STATE_LABELS[item.state]}
              </TableCell>
              <TableCell>{formatReconsentScopes(item.reconsentScopes)}</TableCell>
              <TableCell>{changeNoticeToServer(item.changeNoticeMarkdown ?? "") === null ? "없음" : "있음"}</TableCell>
              <TableCell>
                {item.state === "scheduled" && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-label={`v${item.version} 예약 철회`}
                    onClick={() =>
                      void WithdrawDialog.call({ kind, version: item.version, effectiveAt: item.effectiveAt })
                    }
                  >
                    철회
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

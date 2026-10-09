import { Link } from "@tanstack/react-router";

import { NovelCommentReportActionPanel } from "@/features/act-on-novel-comment-report";
import { NOVEL_COMMENT_DELETED_BY_LABELS } from "@/entities/admin-novel";
import {
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useNovelCommentReportDetailQuery,
  type NovelCommentCurrent,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { QueryState } from "@/shared/ui/QueryState";

const SECTION_CLASS = "flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 wrap-anywhere @xl:p-6";
const LINK_CLASS = "admin-hit-area font-medium text-primary hover:underline focus-visible:underline";

export function NovelCommentReportDetailBody({ reportId }: { reportId: string }) {
  useDocumentTitle("신고 상세");
  const query = useNovelCommentReportDetailQuery(reportId);

  // 이미 처리된 신고도 다시 처리할 수 있어 조치가 늘 있다.
  return (
    <QueryState query={query} skeleton="detail" errorMessage="노벨 댓글 신고를 불러오지 못했어요.">
      {(report) => (
        <DetailLayout
          actions={{
            title: "댓글 조치",
            triggerLabel: "처리하기",
            summary: `신고 ${REPORT_STATUS_LABELS[report.status]}`,
            render: (host) => <NovelCommentReportActionPanel report={report} onSuccess={host.onDone} />,
          }}
        >
          <section className={SECTION_CLASS}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium">
                {REPORT_STATUS_LABELS[report.status]}
              </span>
              <span className="text-sm text-muted-foreground">{formatDateTime(report.createdAt)} 접수</span>
            </div>
            <dl className="grid grid-cols-1 gap-3 text-sm @xl:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">신고 사유</dt>
                <dd>{REPORT_REASON_LABELS[report.reasonCategory]}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">대상 노벨</dt>
                <dd>
                  {report.novelId === null ? (
                    <span className="text-muted-foreground">게시자가 지운 노벨이에요</span>
                  ) : (
                    <Link to="/novels/$novelId" params={{ novelId: report.novelId }} className={LINK_CLASS}>
                      노벨 상세 보기
                    </Link>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">댓글 작성자</dt>
                <dd>
                  <Link to="/users/$userId" params={{ userId: report.commentAuthorUserId }} className={LINK_CLASS}>
                    유저 상세 보기
                  </Link>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">신고자</dt>
                <dd>
                  <Link to="/users/$userId" params={{ userId: report.reporterUserId }} className={LINK_CLASS}>
                    유저 상세 보기
                  </Link>
                </dd>
              </div>
              {!!report.resolvedAt && (
                <div>
                  <dt className="text-muted-foreground">처리일시</dt>
                  <dd>{formatDateTime(report.resolvedAt)}</dd>
                </div>
              )}
            </dl>
          </section>

          <CurrentComment comment={report.comment} />

          <section className={SECTION_CLASS}>
            <h2 className="text-lg font-semibold">신고 당시 원문 증거</h2>
            {report.evidence.available ? (
              <>
                <p className="break-keep text-xs text-muted-foreground">
                  신고 접수 때의 내용이에요. 지금 댓글의 숨김·삭제와 별도로 보관하며{" "}
                  {formatDateTime(report.evidence.expiresAt)}에 만료돼요.
                </p>
                {report.evidence.body ? (
                  <p className="max-w-prose whitespace-pre-wrap break-keep rounded-lg bg-secondary p-3 text-sm text-foreground wrap-anywhere">
                    {report.evidence.body}
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground">비어 있음</p>
                )}
              </>
            ) : (
              <p role="status" className="text-sm text-muted-foreground">
                보관기간이 끝났거나 파기된 원문 증거는 제공하지 않아요.
              </p>
            )}
          </section>
        </DetailLayout>
      )}
    </QueryState>
  );
}

function CurrentComment({ comment }: { comment: NovelCommentCurrent | null }) {
  if (comment === null) {
    return (
      <section className={SECTION_CLASS}>
        <h2 className="text-lg font-semibold">현재 신고 대상 댓글</h2>
        <p className="text-sm text-muted-foreground">
          댓글이 사라졌어요. 작성자가 탈퇴했거나 소설이 지워졌을 수 있어요. 신고 당시 원문은 아래 증거로 봐요.
        </p>
      </section>
    );
  }

  let stateLabel = "표시 중";
  if (comment.deletedAt !== null) {
    stateLabel = comment.deletedBy === null ? "삭제됨" : `삭제됨 · ${NOVEL_COMMENT_DELETED_BY_LABELS[comment.deletedBy]}가 지움`;
  } else if (comment.moderatorHidden) stateLabel = "운영 숨김";

  return (
    <section className={SECTION_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">현재 신고 대상 댓글</h2>
        <span className="text-xs text-muted-foreground">{stateLabel}</span>
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>{comment.authorNickname ?? "(탈퇴한 회원)"}</span>
        <span>{comment.chapterOrdinal}화</span>
        <time dateTime={comment.createdAt}>{formatDateTime(comment.createdAt)}</time>
      </div>
      {comment.deletedAt !== null ? (
        <p className="text-sm text-muted-foreground">지운 댓글이라 본문이 없어요.</p>
      ) : (
        <p className="max-w-prose whitespace-pre-wrap break-keep text-sm wrap-anywhere">{comment.body}</p>
      )}
    </section>
  );
}

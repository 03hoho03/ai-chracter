import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { CommentReportActionPanel } from "@/features/act-on-comment-report";
import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import { REPORT_REASON_LABELS, REPORT_STATUS_LABELS, useCommentReportDetailQuery, type CommentCurrent } from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { QueryState } from "@/shared/ui/QueryState";

const WEB_BASE_URL = import.meta.env.VITE_FRONTEND_BASE_URL ?? "https://ddona.site";

export function CommentReportDetailBody({ reportId }: { reportId: string }) {
  const query = useCommentReportDetailQuery(reportId);
  useDocumentTitle("신고 상세", query.data?.content.name);
  // 이미 처리된 신고도 다시 처리할 수 있어(운영 숨김 해제 등) 조치가 늘 있다.
  return <QueryState query={query} skeleton="detail" errorMessage="댓글 신고를 불러오지 못했어요.">{(report) =>
  <DetailLayout actions={{
    title: "댓글 조치",
    triggerLabel: "처리하기",
    summary: `신고 ${REPORT_STATUS_LABELS[report.status]}`,
    render: (host) => <CommentReportActionPanel report={report} onSuccess={host.onDone} />,
  }}>
    <section className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 wrap-anywhere @xl:p-6">
      <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium">{REPORT_STATUS_LABELS[report.status]}</span>
        <span className="text-sm text-muted-foreground">{formatDateTime(report.createdAt)} 접수</span></div>
      <dl className="grid grid-cols-1 gap-3 text-sm @xl:grid-cols-2">
        <div><dt className="text-muted-foreground">신고 사유</dt><dd>{REPORT_REASON_LABELS[report.reasonCategory]}</dd></div>
        <div><dt className="text-muted-foreground">신고자</dt><dd><Link to="/users/$userId" params={{ userId: report.reporterUserId }} className="font-medium text-primary hover:underline focus-visible:underline">유저 상세 보기</Link></dd></div>
        <div><dt className="text-muted-foreground">대상 작품</dt><dd><Link to="/contents/$contentId" params={{ contentId: report.content.id }} className="break-all font-medium text-primary hover:underline focus-visible:underline">{CONTENT_TYPE_LABELS[report.content.type]} · {report.content.name || "(이름 없음)"}</Link></dd></div>
        {!!report.resolvedAt && <div><dt className="text-muted-foreground">처리일시</dt><dd>{formatDateTime(report.resolvedAt)}</dd></div>}
      </dl>
    </section>
    <CurrentComment comment={report.comment} title="현재 신고 대상 댓글" />
    <section className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 wrap-anywhere @xl:p-6">
      <h2 className="text-lg font-semibold">신고 당시 원문 증거</h2>
      <p className="break-keep text-xs text-muted-foreground">신고 접수 때의 내용이에요. 현재 댓글의 수정·삭제와 별도로 보관하며 {formatDateTime(report.evidence.expiresAt)}에 만료돼요.</p>
      {report.evidence.available ? <>
        {!!report.evidence.body && <p className="whitespace-pre-wrap break-keep text-sm wrap-anywhere">{report.evidence.body}</p>}
        {!!report.evidence.stickerId && <Sticker key={report.evidence.stickerId} id={report.evidence.stickerId} alt="신고 당시 선택한 공식 스티커" />}
        {report.evidence.mentionUserIds.length > 0 && <div className="flex flex-col gap-1 text-xs text-muted-foreground"><p>신고 당시 멘션 계정 ID</p>{report.evidence.mentionUserIds.map((id) => <p key={id} className="break-all">{id}</p>)}</div>}
      </> : <p role="status" className="text-sm text-muted-foreground">보관기간이 끝났거나 파기된 원문 증거는 제공하지 않아요.</p>}
    </section>
    {report.root.id !== report.comment.id && <CurrentComment comment={report.root} title="원댓글 맥락" />}
    {!!report.replyTo && report.replyTo.id !== report.root.id && report.replyTo.id !== report.comment.id && <CurrentComment comment={report.replyTo} title="답글 대상 맥락" />}
  </DetailLayout>}</QueryState>;
}

function Sticker({ id, alt }: { id: string; alt: string }) {
  const [isFailed, setIsFailed] = useState(false);
  return isFailed ? <p className="text-xs text-muted-foreground">{alt} · 이미지를 불러오지 못했어요.</p>
    : <img src={new URL("/comment-stickers/" + encodeURIComponent(id) + ".webp", WEB_BASE_URL).href}
      alt={alt} loading="lazy" decoding="async" width={128} height={128} className="size-32 max-w-full object-contain" onError={() => setIsFailed(true)} />;
}

function CurrentComment({ comment, title }: { comment: CommentCurrent; title: string }) {
  let stateLabel = "표시 중";
  if (comment.deletedAt) stateLabel = "삭제됨";
  else if (comment.moderatorHidden) stateLabel = "운영 숨김";
  else if (comment.creatorHidden) stateLabel = "작가 숨김";
  return <section className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 wrap-anywhere @xl:p-6">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <span className="text-xs text-muted-foreground">{stateLabel}</span>
    </div>
    <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
      {comment.author ? <Link to="/users/$userId" params={{ userId: comment.author.id }} className="font-medium text-primary hover:underline focus-visible:underline">{comment.author.nickname} · 작성자 관리</Link> : <span>삭제된 작성자 정보</span>}
      <time dateTime={comment.createdAt}>{formatDateTime(comment.createdAt)}</time>
      {comment.effectiveSpoiler && <span>스포일러 포함</span>}
      {comment.creatorHidden && comment.moderatorHidden && <span>작가·운영 숨김 모두 적용</span>}
    </div>
    {comment.deletedAt ? <p className="text-sm text-muted-foreground">삭제된 댓글이에요. 원문·스티커·멘션은 제공하지 않아요.</p> : <>
      {!!comment.body && <p className="whitespace-pre-wrap break-keep text-sm wrap-anywhere">{comment.body}</p>}
      {!!comment.sticker && <Sticker key={comment.sticker.id} id={comment.sticker.id} alt={comment.sticker.alt} />}
      {comment.mentions.length > 0 && <p className="flex flex-wrap gap-2 text-xs text-muted-foreground">{comment.mentions.map((author) => <span key={author.id}>@{author.nickname}</span>)}</p>}
    </>}
    <p className="break-all text-xs text-muted-foreground">댓글 ID {comment.id}</p>
  </section>;
}

import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { ChatMessageReportActionPanel } from "@/features/act-on-chat-message-report";
import {
  CHAT_MESSAGE_REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useChatMessageReportDetailQuery,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

const SECTION_CLASS = "flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-2 wrap-anywhere sm:p-6";

/** 대화 열람 링크는 두지 않는다 — 신고 처리에 필요한 맥락은 신고 시점의 사본(응답 + 직전 사용자
 * 메시지)이고, 대화 전체 열람은 사유를 남기는 별도 절차(유저 상세 → 채팅방 열람)를 거친다. */
export function ChatMessageReportDetailBody({ reportId }: { reportId: string }) {
  const query = useChatMessageReportDetailQuery(reportId);
  if (query.isPending) return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  if (query.isError) return <p role="alert" className="text-sm text-destructive-text">채팅 응답 신고를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  const report = query.data;
  return <>
    <section className={SECTION_CLASS}>
      <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium">{REPORT_STATUS_LABELS[report.status]}</span>
        <span className="text-sm text-muted-foreground">{formatDateTime(report.createdAt)} 접수</span></div>
      <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div><dt className="text-muted-foreground">신고 사유</dt><dd>{CHAT_MESSAGE_REPORT_REASON_LABELS[report.reason]}</dd></div>
        <div><dt className="text-muted-foreground">신고자</dt><dd><Link to="/users/$userId" params={{ userId: report.reporterUserId }} className="font-medium text-primary hover:underline focus-visible:underline">유저 상세 보기</Link></dd></div>
        {/* 재생성·메시지 삭제·방 삭제로 원래 응답이 지워져도 신고와 사본은 남는다 — 사본이 지금 대화와
         * 다를 수 있다는 걸 처리자가 알도록 밝힌다. */}
        <div><dt className="text-muted-foreground">원래 응답</dt><dd>{report.chatMessageId === null ? "대화에서 지워졌어요" : "대화에 남아 있어요"}</dd></div>
        {!!report.resolvedAt && <div><dt className="text-muted-foreground">처리일시</dt><dd>{formatDateTime(report.resolvedAt)}</dd></div>}
        <div className="sm:col-span-2"><dt className="text-muted-foreground">신고자 메모</dt>
          <dd className="whitespace-pre-wrap break-keep wrap-anywhere">{report.note ?? <span className="text-muted-foreground">메모 없음</span>}</dd></div>
      </dl>
    </section>
    <section className={SECTION_CLASS}>
      <h2 className="text-lg font-semibold">신고 당시 대화 사본</h2>
      {report.evidence.available ? <>
        {/* 만료 예정일은 사본이 있을 때만 보인다 — 탈퇴로 먼저 파기된 사본에도 미래 날짜가 함께 뜨면
         * 바로 아래 파기 안내와 어긋난다. */}
        <p className="break-keep text-xs text-muted-foreground">신고 접수 때 복사해 둔 내용이에요. 이후 재생성·삭제와 별도로 보관하며 {formatDateTime(report.evidence.expiresAt)}에 만료돼요.</p>
        {/* 빈 경우 안내는 웰 밖에 둔다 — `secondary` 위 `muted-foreground`는 라이트에서 AA 미달이다. */}
        {report.evidence.userMessage === null
          ? <EvidenceEmpty title="직전 사용자 메시지">직전 사용자 메시지 없음(오프닝일 수 있음)</EvidenceEmpty>
          : <EvidenceBlock title="직전 사용자 메시지">{report.evidence.userMessage}</EvidenceBlock>}
        <EvidenceBlock title="신고된 AI 응답">{report.evidence.response}</EvidenceBlock>
      </> : <p role="status" className="text-sm text-muted-foreground">보관기간이 끝났거나 파기된 대화 사본은 제공하지 않아요.</p>}
    </section>
    <ChatMessageReportActionPanel report={report} />
  </>;
}

/** 사본 두 칸은 처리자가 나란히 대조하는 본문이라 같은 웰로 묶는다. card 위 채움은 `secondary`다
 * (`bg-muted`는 card와 값이 같아 사라진다 — `DESIGN.md` Colors 절의 표면 위 채움 규칙). */
function EvidenceBlock({ title, children }: { title: string; children: ReactNode }) {
  return <div className="flex flex-col gap-1">
    <h3 className="text-sm font-medium">{title}</h3>
    <p className="whitespace-pre-wrap break-keep rounded-lg bg-secondary p-3 text-sm text-foreground wrap-anywhere">{children}</p>
  </div>;
}

function EvidenceEmpty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="flex flex-col gap-1">
    <h3 className="text-sm font-medium">{title}</h3>
    <p className="text-sm text-muted-foreground">{children}</p>
  </div>;
}

import type { ReactNode } from "react";

import { assertNever } from "@/shared/lib/assertNever";
import { Button } from "@/shared/ui/Button";

import type { ExportFailure } from "../model/exportFailure";

/** 턴 기록 내보내기를 누른 뒤 화면이 할 말 — 끝났거나, 실패했다. */
export type ExportFeedback = { kind: "done"; path: string } | { kind: "failed"; failure: ExportFailure };

type ExportNoticeProps = {
  feedback: ExportFeedback;
  isPending: boolean;
  onOverwrite: () => void;
  onDismiss: () => void;
};

/**
 * 내보내기 결과 한 줄 — 본문 맨 위에 그 자리에서 펼친다(모달 대신). 거부는 서버 문장을 그대로 두고 그다음 할 일을 붙이며, 파일이
 * 이미 있을 때만 덮어쓸지 묻는다.
 */
export function ExportNotice({ feedback, isPending, onOverwrite, onDismiss }: ExportNoticeProps) {
  const dismiss = (
    <Button onClick={onDismiss} aria-label="내보내기 알림 닫기">
      닫기
    </Button>
  );

  if (feedback.kind === "done") {
    return (
      <NoticeRow role="status" actions={dismiss}>
        <p className="text-ink">
          턴 기록을 내보냈다 — <span className="font-mono break-all">{feedback.path}</span>
        </p>
        <p className="text-ink-secondary">원가·토큰·숨김 스탯·기억 칸을 이 파일로 다시 읽는다.</p>
      </NoticeRow>
    );
  }

  const { failure } = feedback;
  switch (failure.kind) {
    case "confirmOverwrite":
      return (
        <NoticeRow
          role="alert"
          actions={
            <>
              <Button variant="primary" onClick={onOverwrite} disabled={isPending}>
                덮어쓰기
              </Button>
              <Button onClick={onDismiss}>그만두기</Button>
            </>
          }
        >
          <p className="text-ink">{failure.detail}</p>
          <p className="text-ink-secondary">
            턴 기록 파일이 이미 있다. 덮어쓰면 지금 로컬 DB 에 있는 행으로 바뀐다 — 손으로 고쳤거나 지금 DB 에 없는 행은 되돌릴 수
            없다.
          </p>
        </NoticeRow>
      );
    case "refused":
      return (
        <NoticeRow role="alert" actions={dismiss}>
          <p className="text-ink">{failure.detail}</p>
          <p className="text-ink-secondary">{failure.hint}</p>
          <p className="font-mono text-label text-ink-muted">{failure.reason}</p>
        </NoticeRow>
      );
    case "unreachable":
      return (
        <NoticeRow role="alert" actions={dismiss}>
          <p className="text-ink">측정 서버에 연결하지 못했다 — 서버를 띄운 뒤 다시 누른다.</p>
        </NoticeRow>
      );
    case "unknown":
      return (
        <NoticeRow role="alert" actions={dismiss}>
          <p className="text-ink">내보내지 못했다 — {failure.message}</p>
        </NoticeRow>
      );
    default:
      return assertNever(failure);
  }
}

type NoticeRowProps = {
  role: "status" | "alert";
  actions: ReactNode;
  children: ReactNode;
};

function NoticeRow({ role, actions, children }: NoticeRowProps) {
  return (
    <div
      role={role}
      className="flex shrink-0 flex-col gap-2 border-b border-border bg-surface-raised px-3 py-2 text-data sm:flex-row sm:items-start"
    >
      <div className="min-w-0 flex-1 space-y-0.5">{children}</div>
      <div className="flex shrink-0 items-center gap-1">{actions}</div>
    </div>
  );
}

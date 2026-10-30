import type { ReactNode } from "react";

type NoticeProps = {
  title: string;
  children: ReactNode;
  action?: ReactNode;
};

/** 표 대신 본문 자리에 서는 안내(연결 실패·거부·빈 런 루트·없는 런). 무엇이 일어났고 무엇을 하면 되는지를 문장으로 적는다. */
export function Notice({ title, children, action }: NoticeProps) {
  return (
    <div className="h-full overflow-auto bg-surface">
      <div className="mx-auto max-w-xl px-4 py-12">
        <h1 className="text-title text-ink">{title}</h1>
        <div className="mt-3 space-y-3 text-body text-ink-secondary">{children}</div>
        {action !== undefined && <div className="mt-5">{action}</div>}
      </div>
    </div>
  );
}

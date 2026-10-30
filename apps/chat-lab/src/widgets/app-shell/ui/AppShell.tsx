import { Link } from "@tanstack/react-router";
import { Fragment, type ReactNode } from "react";

import { ThemeToggle } from "./ThemeToggle";

/** 빵부스러기 한 마디. 내용(버튼·링크·글)은 화면이 정하고, 구분자와 줄 맞춤은 셸이 맡는다. */
export type Crumb = {
  key: string;
  content: ReactNode;
};

type AppShellProps = {
  crumbs: ReadonlyArray<Crumb>;
  /** 빵부스러기 옆 보조 정보(런 수·탐색 시각 등). 좁은 화면에서는 숨긴다. */
  meta?: ReactNode;
  /** 불일치·주의 배지 자리. */
  badges?: ReactNode;
  /** 화면별 행동 버튼(새로 훑기 등). */
  actions?: ReactNode;
  /** 아래 상태 줄의 단축키 힌트. */
  hints: ReactNode;
  children: ReactNode;
};

/**
 * 뷰포트에 고정된 셸 — 위 헤더 한 줄, 아래 상태 줄, 그 사이 본문. 문서 전체는 스크롤하지 않고 본문 안의 열들이 각자 스크롤해서,
 * 헤더·상태 줄과 다른 열이 늘 제자리에 있다.
 */
export function AppShell({ crumbs, meta, badges, actions, hints, children }: AppShellProps) {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-10 shrink-0 items-center gap-3 border-b border-border bg-background px-3">
        <Link
          to="/"
          className="shrink-0 rounded-sm font-mono text-data font-semibold text-ink-secondary hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          chat-lab
        </Link>
        <nav aria-label="경로" className="min-w-0">
          <ol className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap">
            {crumbs.map((crumb) => (
              <Fragment key={crumb.key}>
                <li aria-hidden="true" className="shrink-0 text-ink-muted">
                  /
                </li>
                <li className="min-w-0 truncate">{crumb.content}</li>
              </Fragment>
            ))}
          </ol>
        </nav>
        {meta !== undefined && <span className="hidden shrink-0 text-data text-ink-muted lg:inline">{meta}</span>}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {badges}
          {actions}
          <ThemeToggle />
        </div>
      </header>
      <main className="min-h-0 flex-1">{children}</main>
      <footer className="hidden h-6 shrink-0 items-center gap-4 border-t border-border bg-background px-3 text-label text-ink-muted md:flex">
        {hints}
      </footer>
    </div>
  );
}

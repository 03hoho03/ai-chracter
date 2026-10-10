import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, History, Loader2, Plus } from "lucide-react";
import type { ReactNode, RefObject } from "react";

import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";

type NovelBoardTopBarProps = {
  novelId: string;
  /** 소설 제목. 아직 모르면(상세를 받는 중, `undefined`) 막대를 그린다. 못 보이는 상태(없음·잠김·실패)에서는 그 안내가
   * 페이지 제목을 가지므로 `null` — 제목 자리를 비운다. */
  title: string | null | undefined;
  /** 카드 자리 자동 저장 안내. 캔버스가 있을 때만 참인 문장이라 그때만 준다. */
  autosaveNotice?: string;
  /** 버전 패널을 여닫는 토글. 상세를 받기 전에는 없다. */
  versions?: { isOpen: boolean; onToggle: () => void };
  /** 다음 화 만들기. 상세를 받기 전에는 없다. */
  create?: CreateChapterAction;
  /** 노벨 공개 버튼(ghost) — 공개는 다른 기능이라 화면이 넣는다. 버전 앞에 놓인다. */
  publishAction?: ReactNode;
};

type CreateChapterAction = {
  flow: NovelChapterJobFlow;
  hasChapters: boolean;
  /** 못 누르는 이유 문장(작업 줄 안). 진행 중이면 진행 줄을 가리킨다. */
  blockedReasonId: string | undefined;
  /** 작업 줄의 "다시 시도"가 사라지기 전에 포커스를 옮겨 둘 자리. */
  buttonRef: RefObject<HTMLButtonElement | null>;
};

/**
 * 편집 보드의 상단 바. 전역 헤더 대신 같은 56px(`h-14`) 자리를 쓰는 전용 바이고 클래스는 빌더 상단 바와 같다
 * (안쪽 바가 뷰포트를 꽉 채우고 `px-4 sm:px-6`만 — 보드에는 좌측 패널이 없다) — 그 아래 `h-below-header` 높이 계산이
 * 그대로 맞는다.
 *
 * 뒤로가기는 기록 뒤로가 아니라 작품 정보로 가는 고정 목적지다 — 보드에 오는 길이 여럿이다(작품 정보, 읽기 화면 끝의
 * "편집"). 이 화면의 유일한 솔리드 채움은 "다음 화 만들기"이고, 버전은 윤곽 토글, 노벨 공개는 ghost 다. `sm` 미만에서는 두 버튼의
 * 라벨을 숨기고 아이콘과 접근 이름만 남긴다(빌더 상단 바와 같은 규칙).
 */
export function NovelBoardTopBar({ novelId, title, autosaveNotice, versions, create, publishAction }: NovelBoardTopBarProps) {
  return (
    <header className="sticky top-0 z-30 h-14 shrink-0 border-b border-border bg-background">
      <div className="flex h-14 items-center gap-2 px-4 sm:gap-3 sm:px-6">
        <Button asChild variant="ghost" size="icon" aria-label="작품 정보" className="shrink-0">
          <Link to="/novels/$novelId" params={{ novelId }}>
            <ArrowLeft aria-hidden className="size-4" />
          </Link>
        </Button>
        {title === undefined && <div aria-hidden className="h-6 w-40 animate-pulse rounded-lg bg-muted" />}
        {typeof title === "string" && (
          <h1 className="min-w-0 truncate text-xl font-semibold tracking-tight text-foreground">{title}</h1>
        )}
        <div className="min-w-0 flex-1">
          {!!autosaveNotice && <p className="hidden truncate text-xs text-muted-foreground sm:block">{autosaveNotice}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          {publishAction}
          {versions !== undefined && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-pressed={versions.isOpen}
              aria-label="버전"
              data-board-key="versions"
              className="aria-pressed:border-ring"
              onClick={versions.onToggle}
            >
              <History aria-hidden />
              <span className="hidden sm:inline">버전</span>
            </Button>
          )}
          {create !== undefined && <CreateChapterButton {...create} />}
        </div>
      </div>
    </header>
  );
}

/** "다음 화 만들기". 못 누르는 동안에도 `disabled` 가 아니라 `aria-disabled` 다 — `disabled` 는 누른 순간 포커스를
 * 날리고 이유를 말하지 않는다. 이유와 진행은 패널 맨 위 작업 줄이 진다. 준비 중(이름·경계 고르기·확인)에는 아이콘만
 * 스피너로 바뀌고 라벨은 그대로라 버튼 폭이 흔들리지 않는다 — 스피너는 진행 표시라 동작 줄이기 설정에서도 돈다. */
function CreateChapterButton({ flow, hasChapters, blockedReasonId, buttonRef }: CreateChapterAction) {
  const isBlocked = flow.isBusy || flow.isRoomGone;
  const isPreparing = flow.preparing === "create";
  const label = hasChapters ? "다음 화 만들기" : "첫 화 만들기";
  const describedBy = blockedReasonId ?? (flow.isJobRunning ? flow.statusId : undefined);

  return (
    <Button
      ref={buttonRef}
      type="button"
      size="sm"
      aria-label={label}
      aria-disabled={isBlocked}
      aria-describedby={isBlocked ? describedBy : undefined}
      className="aria-disabled:opacity-65"
      onClick={() => {
        if (isBlocked) return;
        void flow.startCreate();
      }}
    >
      {isPreparing ? <Loader2 aria-hidden className="animate-spin" /> : <Plus aria-hidden />}
      <span className="hidden sm:inline">{label}</span>
    </Button>
  );
}

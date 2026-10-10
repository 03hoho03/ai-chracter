import type { ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

type BuilderTopBarProps = {
  /** 빌더 라우트(`/builder`, `/builder/$type/$draftId`)의 페이지 제목. */
  title: string;
  /** 미리보기/임시저장/발행 같은 우측 액션 버튼들. 액션이 없는 화면(`BuilderTypeSelectPage`)에서는
   * 생략한다. */
  actions?: ReactNode;
  /** "변경사항은 자동으로 저장돼요." 같은 저장 계약 안내문. 폼이 있는 셸에서만 의미가 있다. */
  autosaveNotice?: string;
};

/**
 * 빌더 라우트는 전역 Header(`routes/__root.tsx`) 대신 이
 * 전용 상단바를 쓴다(크랙 실측 기준). 전역 헤더와 같은 구조(바깥 `border-b` + 안쪽 `h-14`, 총 57px)라 같은 자리를
 * 차지하므로 BuilderLayout의 `h-below-header` 높이 계산이 그대로 맞는다 — `h-14`와 `border-b`를 한 요소에 걸면
 * border-box 라 56px 가 되어 그 아래 화면이 1px 짧아진다.
 *
 * 안쪽 바가 뷰포트를 꽉 채운다(`mx-auto max-w-*` 없이 `px-4 sm:px-6`만 — 전역 헤더 안쪽 바와 같은 클래스이고, 빌더
 * 라우트에는 좌측 패널이 없어 그 폭이 뷰포트다). lg 이상에서는
 * `BuilderLayout`이 폼 열을 왼쪽에 붙이고 같은 `px-6`을 쓰므로 뒤로가기 버튼 left와 탭 목록 left가
 * 어느 폭에서나 같다 — 이 패딩을 바꾸면 그쪽도 함께 바꿔야 한다. lg 미만은 본문이 `max-w-2xl`로
 * 가운데 정렬돼 두 left가 `(폭 − 672) / 2` 만큼 갈린다(받아들인 어긋남, DESIGN.md Layout containers 절).
 *
 * 뒤로가기 목적지는 인터뷰로 확정된 `/my`(내 작품) 하나뿐이라 prop으로 받지 않는다. 본문이 1열인 `lg` 미만에서는
 * 액션 버튼의 라벨과 자동저장 안내문을 숨기고 아이콘만 남긴다(`hidden lg:inline`) — 상단바가 데스크톱 구성으로
 * 바뀌는 경계를 본문이 2단으로 바뀌는 경계와 맞춘다(DESIGN.md Navigation 절). 좌우 여백(`px-4 sm:px-6`)은 전역 헤더와
 * 같은 `sm` 경계 그대로다. 저장 상태는 라벨이 숨은 폭에서도 임시저장 버튼의 아이콘이 보인다.
 */
export function BuilderTopBar({ title, actions, autosaveNotice }: BuilderTopBarProps) {
  return (
    <header className="sticky top-0 z-30 shrink-0 border-b border-border bg-background">
      <div className="flex h-14 items-center gap-2 px-4 sm:gap-3 sm:px-6">
        <Button asChild variant="ghost" size="icon" aria-label="뒤로가기" className="shrink-0 pointer-coarse:size-10">
          <Link to="/my">
            <ArrowLeft aria-hidden className="size-4" />
          </Link>
        </Button>
        {/* 폭이 모자라면 액션 넷(작성 가이드·미리보기·임시저장·발행) 대신 제목이 말줄임으로 줄어든다 — 제목은
            고정문이라 잘려도 잃는 정보가 작고, 줄지 않으면 액션 묶음이 바 밖으로 넘친다. 실측으로 390·360·320px
            모두 넘침이 없었고, 320px 에서는 제목 칸이 약 40px(손가락 포인터에서 버튼이 40px 로 커지면 약 36px)로 줄어 말줄임된다. */}
        <h1 className="min-w-0 truncate text-xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        <div className="min-w-0 flex-1">
          {!!autosaveNotice && <p className="hidden truncate text-xs text-muted-foreground lg:block">{autosaveNotice}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">{actions}</div>}
      </div>
    </header>
  );
}

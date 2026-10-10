import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, ErrorComponent, Outlet, useRouterState } from "@tanstack/react-router";

import { ChangeContentVisibilityModal } from "@/features/change-content-visibility";
import { ChangeNovelPermissionModal } from "@/features/change-novel-permission";
import { ChangeStartingSetupModal, ConfirmStartingSetupChangeModal } from "@/features/change-starting-setup";
import { FirstPersonaNameModal } from "@/features/choose-start-persona";
import { ImageCropModal } from "@/features/crop-image";
import { MediaBookConfirmModal, MediaBookOverwriteModal, MediaTagPickerModal } from "@/features/edit-media-book";
import { EndingCollectionModal } from "@/features/ending-collection";
import { ImageArchiveModal, StoryImageArchiveModal } from "@/features/image-archive";
import { ConfirmChatRoomActionModal } from "@/features/manage-chat-room";
import { DeletePersonaModal } from "@/features/manage-persona";
import { DeleteContentDraftModal, ResetContentDraftModal } from "@/features/manage-content-draft";
import { PlayGuideModal } from "@/features/play-guide";
import { PurchaseConfirmDialog } from "@/features/purchase-clover";
import { ReportChatMessageModal } from "@/features/report-chat-message";
import { ReportContentModal } from "@/features/report-content";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";
import { AppealModal } from "@/features/submit-appeal";
import { UpdateInfoModal } from "@/features/update-info";
import { ContentDetailModalOutlet } from "@/widgets/content-detail";
import { Header, isGlobalHeaderHidden, SidePanel, useIsSidePanelLayout, useSidePanelCollapse } from "@/widgets/header";
import { ReconsentModal } from "@/widgets/reconsent-legal";
import { isSiteFooterHidden, SiteFooter } from "@/widgets/site-footer";
import { ConfirmCloverSpendModal } from "@/features/confirm-clover-spend";
import { ConfirmChapterSpendModal, ConfirmNovelSpendModal } from "@/features/confirm-novel-spend";
import { ChapterBoundaryModal, ProtagonistNameModal } from "@/features/create-novel-chapter";
import { DeleteLastChapterModal, DeleteNovelModal } from "@/features/delete-novel";
import { AiEditInstructionModal, DiscardManualEditModal } from "@/features/edit-novel-chapter";
import { NovelRevisionHistoryModal } from "@/features/novel-revision-history";
import { CommentActionModal, CommentLoginModal, CommentReportModal } from "@/features/work-comments";
import { ContentComments } from "@/widgets/content-comments";
import { NotFoundPage } from "@/pages/not-found";
import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";
import { SkipLink } from "@/shared/ui/SkipLink";

export type RouterContext = {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
  // 라우터의 `defaultOnCatch`(router.tsx)만 설정하면 절대 호출되지 않는다 —
  // `Match.js`의 `MatchView`가 `route.options.errorComponent ?? router.options.defaultErrorComponent`가
  // 없으면 `CatchBoundary` 대신 `SafeFragment`를 쓰는데, `SafeFragment`는 `children` 외
  // props를 전부 버려서 `onCatch`가 붙을 자리 자체가 없다(설치된 소스로 확인). 그래서 여기
  // 루트 라우트에만 `errorComponent`를 건다. 여기 넘긴 `ErrorComponent`는 `@tanstack/react-router`가
  // `defaultErrorComponent`/전역 CatchBoundary 미설정 시 실제로 렌더하는 바로 그 컴포넌트라
  // (`CatchBoundary.js`에서 export) 화면에 보이는 에러 UI는 이 전후로 달라지지 않는다.
  // 루트에만 걸어 하위 라우트는 여전히 `SafeFragment`이므로 에러가 루트까지 버블링돼
  // 오늘과 동일하게 헤더·좌측 패널 포함 전체가 교체된다(블라스트 반경 불변).
  errorComponent: ErrorComponent,
  // 지정하지 않으면 라우터 기본값인 영문 "Not Found" 한 줄이 나간다. Worker는 모르는 경로에 셸 본문을 404로
  // 주므로(`worker/routes.ts`) 사용자가 보는 건 이 화면이다.
  notFoundComponent: NotFoundPage,
});

function RootComponent() {
  // 전역 크롬(헤더·좌측 패널)을 건너뛰는 라우트(빌더·소설 화 읽기·소설 편집 보드)와 그 이유는 `isGlobalHeaderHidden` 에
  // 모아 둔다 — 헤더와 패널이 같은 판정을 읽어, 헤더 없는 화면에 패널만 남는 일이 없다. 빌더는 같은 56px(`h-14`) 자리에
  // 전용 상단바(`features/build-common`의 `BuilderTopBar`)를 두므로 헤더를 빼도 `calc(100dvh-3.5rem)` 높이 계산은
  // 그대로다(DESIGN.md Navigation 절). 판정은 경로 매칭 대신 pathname 으로 한다 — `useRouterState`가 이미 헤더
  // 자신(SearchInlineExpand)·채팅 리스트에서 쓰는 방식이라 새 패턴을 들이지 않는다.
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const hasGlobalChrome = !isGlobalHeaderHidden(pathname);
  // 좌측 패널은 `lg` 이상에서만 마운트한다 — CSS 로 숨기면 `lg` 미만에서도 보이지 않는 최근 대화 조회가 화면마다 돈다.
  // 접힘 상태는 패널이 아니라 여기(늘 마운트된 셸)가 든다: 창을 `lg` 아래로 줄였다 늘려도 채팅에서 펼친 상태가 남고,
  // 패널이 없는 동안의 화면 이동도 따라간다.
  const isSidePanelLayout = useIsSidePanelLayout();
  const sidePanelCollapse = useSidePanelCollapse(pathname);

  return (
    <>
      {hasGlobalChrome && <SkipLink />}
      {/* `lg` 이상은 [좌측 패널 | 오른쪽 열(헤더·페이지·푸터)], 그 아래는 오른쪽 열 하나다. 스크롤 컨테이너는 window 하나다 —
          이 셸과 오른쪽 열에 overflow 를 걸지 않는다. 걸면 헤더·패널의 sticky 가 죽고, 라우터의 이동 시 맨 위 리셋과 소설
          뷰어의 읽은 위치(`window.scrollY`)가 기준을 잃는다. 오른쪽 열의 `min-w-0` 은 가로로 넓은 내용(이미지 스튜디오
          3열 등)이 열을 밀어 패널 밖으로 넘치지 않게 한다. 페이지 영역을 `flex-1`로 늘려 짧은 페이지에서도 푸터가
          뷰포트 바닥에 앉게 한다. 아웃렛은 평범한 블록 안에 둔다 — 각 페이지의 `<main>`은 `w-full` 없이 `mx-auto`로
          가운데 놓이므로, flex 아이템이 되면 내용 폭으로 줄어든다. 그 블록이 건너뛰기 링크의 도착지다(`tabIndex=-1`). */}
      <div className="flex min-h-dvh">
        {hasGlobalChrome && isSidePanelLayout && (
          <SidePanel
            isCollapsed={sidePanelCollapse.isCollapsed}
            isToggled={sidePanelCollapse.isToggled}
            onToggle={sidePanelCollapse.toggle}
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          {hasGlobalChrome && <Header />}
          <div id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 outline-none">
            <Outlet />
          </div>
          {!isSiteFooterHidden(pathname) && <SiteFooter />}
        </div>
      </div>
      <ContentDetailModalOutlet renderComments={(id) => <ContentComments key={id} contentId={id} />} />
      <CommentActionModal />
      <CommentLoginModal />
      <CommentReportModal />
      <ReportContentModal />
      <ReportChatMessageModal />
      <ConfirmChatRoomActionModal />
      <PurchaseConfirmDialog />
      <PlayGuideModal />
      <EndingCollectionModal />
      <ImageArchiveModal />
      <StoryImageArchiveModal />
      <ImageCropModal />
      <UpdateInfoModal />
      <ChangeStartingSetupModal />
      <ConfirmStartingSetupChangeModal />
      <GeneratedImagePickerModal />
      <MediaBookConfirmModal />
      <MediaBookOverwriteModal />
      <MediaTagPickerModal />
      <AppealModal />
      <ChangeContentVisibilityModal />
      <ChangeNovelPermissionModal />
      <DeleteContentDraftModal />
      <ResetContentDraftModal />
      <ReconsentModal />
      <ConfirmCloverSpendModal />
      <ConfirmNovelSpendModal />
      <ConfirmChapterSpendModal />
      <ProtagonistNameModal />
      <ChapterBoundaryModal />
      <AiEditInstructionModal />
      <DiscardManualEditModal />
      <NovelRevisionHistoryModal />
      <DeleteLastChapterModal />
      <DeleteNovelModal />
      <DeletePersonaModal />
      <FirstPersonaNameModal />
    </>
  );
}

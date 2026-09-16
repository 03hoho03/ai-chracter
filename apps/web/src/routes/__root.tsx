import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, ErrorComponent, Outlet, useRouterState } from "@tanstack/react-router";

import { ChangeContentVisibilityModal } from "@/features/change-content-visibility";
import { ChangeStartingSetupModal, ConfirmStartingSetupChangeModal } from "@/features/change-starting-setup";
import { ImageCropModal } from "@/features/crop-image";
import { EndingCollectionModal } from "@/features/ending-collection";
import { ImageArchiveModal } from "@/features/image-archive";
import { ConfirmChatRoomActionModal } from "@/features/manage-chat-room";
import { DeleteContentDraftModal, ResetContentDraftModal } from "@/features/manage-content-draft";
import { PlayGuideModal } from "@/features/play-guide";
import { ReportContentModal } from "@/features/report-content";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";
import { AppealModal } from "@/features/submit-appeal";
import { UpdateInfoModal } from "@/features/update-info";
import { ContentDetailModalOutlet } from "@/widgets/content-detail";
import { Header } from "@/widgets/header";
import { ReconsentModal } from "@/widgets/reconsent-legal";

export type RouterContext = {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
  // O-10: 라우터의 `defaultOnCatch`(router.tsx)만 설정하면 절대 호출되지 않는다 —
  // `Match.js`의 `MatchView`가 `route.options.errorComponent ?? router.options.defaultErrorComponent`가
  // 없으면 `CatchBoundary` 대신 `SafeFragment`를 쓰는데, `SafeFragment`는 `children` 외
  // props를 전부 버려서 `onCatch`가 붙을 자리 자체가 없다(설치된 소스로 확인). 그래서 여기
  // 루트 라우트에만 `errorComponent`를 건다. 여기 넘긴 `ErrorComponent`는 `@tanstack/react-router`가
  // `defaultErrorComponent`/전역 CatchBoundary 미설정 시 실제로 렌더하는 바로 그 컴포넌트라
  // (`CatchBoundary.js`에서 export) 화면에 보이는 에러 UI는 이 전후로 달라지지 않는다.
  // 루트에만 걸어 하위 라우트는 여전히 `SafeFragment`이므로 에러가 루트까지 버블링돼
  // 오늘과 동일하게 헤더 포함 전체가 교체된다(블라스트 반경 불변).
  errorComponent: ErrorComponent,
});

function RootComponent() {
  // builder-preview-validation(피드백 2) — 빌더 라우트(`/builder`, `/builder/$type/$draftId`)는 전역
  // Header 대신 전용 상단바(`features/build-common`의 `BuilderTopBar`)를 쓴다. 두 상단바가 같은 56px
  // (`h-14`) 자리를 차지하므로 헤더를 빼도 `calc(100dvh-3.5rem)` 높이 계산은 그대로다(DESIGN.md
  // §Navigation). 판정은 경로 매칭 대신 pathname 접두사로 한다 — `useRouterState`가 이미 헤더
  // 자신(SearchInlineExpand)·채팅 리스트에서 쓰는 방식이라 새 패턴을 들이지 않는다.
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isBuilderRoute = pathname === "/builder" || pathname.startsWith("/builder/");

  return (
    <>
      {!isBuilderRoute && <Header />}
      <Outlet />
      <ContentDetailModalOutlet />
      <ReportContentModal />
      <ConfirmChatRoomActionModal />
      <PlayGuideModal />
      <EndingCollectionModal />
      <ImageArchiveModal />
      <ImageCropModal />
      <UpdateInfoModal />
      <ChangeStartingSetupModal />
      <ConfirmStartingSetupChangeModal />
      <GeneratedImagePickerModal />
      <AppealModal />
      <ChangeContentVisibilityModal />
      <DeleteContentDraftModal />
      <ResetContentDraftModal />
      <ReconsentModal />
    </>
  );
}

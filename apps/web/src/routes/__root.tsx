import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet, useRouterState } from "@tanstack/react-router";

import { ChangeContentVisibilityModal } from "@/features/change-content-visibility";
import { ChangeStartingSetupModal, ConfirmStartingSetupChangeModal } from "@/features/change-starting-setup";
import { EndingCollectionModal } from "@/features/ending-collection";
import { ImageArchiveModal } from "@/features/image-archive";
import { ConfirmChatRoomActionModal } from "@/features/manage-chat-room";
import { DeleteContentDraftModal, ResetContentDraftModal } from "@/features/manage-content-draft";
import { PlayGuideModal } from "@/features/play-guide";
import { ReconsentModal } from "@/features/reconsent-legal";
import { ReportContentModal } from "@/features/report-content";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";
import { AppealModal } from "@/features/submit-appeal";
import { UpdateInfoModal } from "@/features/update-info";
import { ContentDetailModalOutlet } from "@/widgets/content-detail";
import { Header } from "@/widgets/header";

export type RouterContext = {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});

function RootComponent() {
  // builder-preview-validation(피드백 2) — 빌더 라우트(`/builder`, `/builder/$type/$draftId`)는 전역
  // Header 대신 전용 상단바(`widgets/build-common`의 `BuilderTopBar`)를 쓴다. 두 상단바가 같은 56px
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

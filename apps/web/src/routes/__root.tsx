import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";

import { ChangeContentVisibilityModal } from "@/features/change-content-visibility";
import { ChangeStartingSetupModal, ConfirmStartingSetupChangeModal } from "@/features/change-starting-setup";
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

export type RouterContext = {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});

function RootComponent() {
  return (
    <>
      <Header />
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
    </>
  );
}

import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";

import { ContentDetailModalOutlet } from "../widgets/content-detail";
import { Header } from "../widgets/header";
import { EndingCollectionModal } from "../features/ending-collection";
import { ImageArchiveModal } from "../features/image-archive";
import { ConfirmChatRoomActionModal } from "../features/manage-chat-room";
import { PlayGuideModal } from "../features/play-guide";
import { ReportContentModal } from "../features/report-content";
import { UpdateInfoModal } from "../features/update-info";

export interface RouterContext {
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
    </>
  );
}

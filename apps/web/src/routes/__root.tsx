import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";

import { ContentDetailModalOutlet } from "../widgets/content-detail";
import { Header } from "../widgets/header";
import { ConfirmChatRoomActionModal } from "../features/manage-chat-room";
import { ReportContentModal } from "../features/report-content";

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
    </>
  );
}

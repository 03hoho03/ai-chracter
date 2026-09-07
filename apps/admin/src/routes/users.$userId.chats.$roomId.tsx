import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ChatMessagesPage } from "../pages/chat-messages";

export const Route = createFileRoute("/users/$userId/chats/$roomId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { userId, roomId } = Route.useParams();
  return <ChatMessagesPage userId={userId} roomId={roomId} />;
}

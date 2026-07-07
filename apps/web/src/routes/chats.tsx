import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ChatsPage } from "../pages/chats";

export const Route = createFileRoute("/chats")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: ChatsPage,
});

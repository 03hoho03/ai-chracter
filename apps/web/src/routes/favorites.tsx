import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { FavoritesPage } from "../pages/favorites";

export const Route = createFileRoute("/favorites")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: FavoritesPage,
});

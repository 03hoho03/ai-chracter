import { createFileRoute } from "@tanstack/react-router";

import { UiDemoPage } from "../pages/ui-demo";

export const Route = createFileRoute("/ui-demo")({
  component: UiDemoPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { ForgotPasswordPage } from "../pages/forgot-password";

export const Route = createFileRoute("/forgot-password")({
  component: ForgotPasswordPage,
});

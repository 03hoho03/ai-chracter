import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { OnboardingGooglePage } from "../pages/onboarding-google";

const onboardingGoogleSearchSchema = z.object({
  token: z.string(),
});

export const Route = createFileRoute("/onboarding/google")({
  validateSearch: onboardingGoogleSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const { token } = Route.useSearch();
  return <OnboardingGooglePage token={token} />;
}

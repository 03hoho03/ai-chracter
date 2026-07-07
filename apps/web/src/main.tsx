import "@ai-character-chat/ui/globals.css";

import { Toaster } from "@ai-character-chat/ui/components/sonner";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "./app/providers";
import { router } from "./app/router";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} />
      <Toaster />
    </AppProviders>
  </StrictMode>,
);

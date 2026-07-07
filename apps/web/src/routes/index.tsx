import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { HomePage } from "../pages/home";

// techspec-global-nav-profile.md §1.2 — 헤더 검색 인라인 익스팬드가 갱신하는 검색 파라미터.
// 실제 검색 결과 필터링은 홈 화면 스토리(US-037+)에서 이 값을 소비한다.
const homeSearchSchema = z.object({
  q: z.string().optional(),
});

export const Route = createFileRoute("/")({
  validateSearch: homeSearchSchema,
  component: HomePage,
});

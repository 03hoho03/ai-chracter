import { createFileRoute } from "@tanstack/react-router";

import { AttendancePage } from "@/pages/attendance";

/** 출석판. `requireSession` 이 없다 — 비로그인도 공개 보상표로 판을 보고 거기서 로그인을 권한다. 판 응답이 404 인지(찾을
 * 수 없는 화면을 그릴지)는 페이지가 판정한다(여기서 판 응답을 기다리면 첫 화면이 그만큼 멈춘다). */
export const Route = createFileRoute("/attendance")({
  component: AttendancePage,
});

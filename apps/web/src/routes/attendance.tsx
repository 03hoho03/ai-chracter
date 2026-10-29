import { createFileRoute } from "@tanstack/react-router";

import { AttendancePage } from "@/pages/attendance";

/** 출석판. `requireSession` 이 없다 — 비로그인도 공개 보상표로 판을 보고 거기서 로그인을 권한다. 출석 스위치가 꺼졌는지는
 * 페이지가 판정한다(여기서 가격 응답을 기다리면 첫 화면이 그만큼 멈춘다). */
export const Route = createFileRoute("/attendance")({
  component: AttendancePage,
});

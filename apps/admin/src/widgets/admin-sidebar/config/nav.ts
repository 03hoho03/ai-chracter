export type AdminNavItem = {
  label: string;
  to: "/" | "/reports" | "/appeals" | "/usage-metrics";
};

/** 지금 존재하는 화면만 넣는다. 작품/유저/약관은 각 단계에서 라우트가 생긴 뒤 추가한다. */
export const ADMIN_NAV_ITEMS: AdminNavItem[] = [
  { label: "홈", to: "/" },
  { label: "신고 관리", to: "/reports" },
  { label: "이의제기 검토", to: "/appeals" },
  { label: "사용량 모니터링", to: "/usage-metrics" },
];

export type AdminNavItem = {
  label: string;
  to: "/" | "/reports" | "/appeals" | "/usage-metrics" | "/contents" | "/users" | "/legal";
};

export const ADMIN_NAV_ITEMS: AdminNavItem[] = [
  { label: "대시보드", to: "/" },
  { label: "작품 관리", to: "/contents" },
  { label: "유저 관리", to: "/users" },
  { label: "신고 관리", to: "/reports" },
  { label: "이의제기 검토", to: "/appeals" },
  { label: "사용량 모니터링", to: "/usage-metrics" },
  { label: "약관 관리", to: "/legal" },
];

import {
  Banknote,
  BookOpen,
  BookOpenText,
  ChartLine,
  Flag,
  HandCoins,
  Images,
  Inbox,
  LayoutDashboard,
  Megaphone,
  Scale,
  ScrollText,
  SquareTerminal,
  Users,
} from "lucide-react";

// 그룹 배열 전체에 `as const` — 원소 객체와 `to` 가 리터럴로 남아 `Link` 의 경로 유니온과 대조된다.
// 없는 경로를 넣으면 타입 에러는 이 파일이 아니라 `Link` 를 그리는 `ui/AdminNavList.tsx` 에 뜬다.
export const ADMIN_NAV_GROUPS = [
  {
    label: "개요",
    items: [
      { label: "대시보드", to: "/", icon: LayoutDashboard },
      { label: "사용량 모니터링", to: "/usage-metrics", icon: ChartLine },
    ],
  },
  {
    label: "검토 큐",
    items: [
      { label: "신고 관리", to: "/reports", icon: Flag },
      { label: "이의제기 검토", to: "/appeals", icon: Scale },
      { label: "정산 신청 검토", to: "/creator-payout-applications", icon: HandCoins },
      { label: "지급 처리", to: "/creator-payouts", icon: Banknote },
      { label: "문의 관리", to: "/inquiries", icon: Inbox },
    ],
  },
  {
    label: "콘텐츠·유저",
    items: [
      { label: "작품 관리", to: "/contents", icon: BookOpen },
      { label: "노벨 관리", to: "/novels", icon: BookOpenText },
      { label: "유저 관리", to: "/users", icon: Users },
      { label: "이미지 생성 관리", to: "/image-generations", icon: Images },
    ],
  },
  {
    label: "서비스 설정",
    items: [
      { label: "공지 관리", to: "/notices", icon: Megaphone },
      { label: "약관 관리", to: "/legal", icon: ScrollText },
      { label: "프롬프트 관리", to: "/prompt-sets", icon: SquareTerminal },
    ],
  },
] as const;

export type AdminNavGroup = (typeof ADMIN_NAV_GROUPS)[number];
export type AdminNavItem = AdminNavGroup["items"][number];
export type AdminNavTo = AdminNavItem["to"];

/** 상단바 화면명처럼 그룹 없이 훑는 소비처용. 원소 타입은 리터럴 유니온 그대로다. */
// `flatMap` 은 그룹마다 다른 튜플 타입에서 원소 타입을 첫 그룹 것으로만 추론하므로 제네릭을 직접 준다.
export const ADMIN_NAV_ITEMS: readonly AdminNavItem[] = ADMIN_NAV_GROUPS.flatMap<AdminNavItem>((group) => group.items);

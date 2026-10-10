import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { BUSINESS_INFO, describeMailOrderReport } from "@/shared/config/businessInfo";
import { SITE_NAME } from "@/shared/config/site";
import { SUPPORT_DESTINATIONS, type SupportDestinationKey } from "@/shared/config/supportDestinations";

const FOOTER_LINK_KEYS = [
  "about",
  "terms",
  "privacy",
  "operation-policy",
  "youth-policy",
  "refund-policy",
  "clover-pricing",
  "notices",
  "inquiry-new",
] as const satisfies readonly SupportDestinationKey[];

const LINK_CLASS =
  "whitespace-nowrap rounded-sm text-xs text-muted-foreground motion-safe:transition-colors hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * 문서 끝에 놓이는 정보 푸터. 고정하지 않는다 — 루트 레이아웃이 페이지 영역을 늘려 짧은 페이지에서는 뷰포트
 * 바닥에, 긴 페이지에서는 끝까지 스크롤해야 만난다.
 *
 * 링크 아래에 운영자 정보(상호·대표자·사업자등록번호·통신판매업·주소·전화·이메일·호스팅 제공자)를 항목 이름과
 * 값으로 나눠(`<dl>`) 싣는다. 이름과 값은 같은 `muted` 잉크다 — 이름을 굵게 하거나 밝히면 처리방침 링크의 강조가
 * 더는 하나가 아니게 된다.
 *
 * 강조는 `개인정보처리방침` 하나뿐이다 — 처리방침은 첫 화면에서 다른 링크와 구별돼 찾을 수 있어야 한다. 색은
 * `primary`가 아니라 밝기 천장(`text-foreground`)과 굵기로 올린다 — `primary`는 이 시스템의 유일한 강조색이다.
 *
 * 콘텐츠 상세화면의 `lg` 미만에서는 플레이 바가 바닥에 `fixed`로 붙고 이 푸터가 그 화면 문서의 마지막
 * 요소다. 그래서 바 높이 + safe-area 만큼의 아래 여백을 여기서 져야 마지막 줄이 바에 가려지지 않는다. 바는 캐릭터가
 * 81px(경계선 1 + p-4 16×2 + 버튼 48), 스토리가 시작 설정 이름 한 줄이 더해져 약 104px(390px 실측 103.66)이라 큰 쪽에
 * 맞춘 7rem(112px)을 둔다 — 경로가 작품 종류를 가르지 않아 캐릭터 화면은 바 위로 약 31px가 빈다. `lg`부터는 바가 본문
 * 안 인라인으로 돌아가 보통 여백으로 되돌린다.
 */
export function SiteFooter() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const hasFixedPlayBarBelow = pathname.startsWith("/content/");

  return (
    <footer className="border-t border-border">
      <div
        className={cn(
          "mx-auto flex max-w-5xl flex-col gap-3 px-4 pt-6 sm:px-6",
          hasFixedPlayBarBelow ? "pb-[calc(7rem+env(safe-area-inset-bottom))] lg:pb-4-safe" : "pb-4-safe",
        )}
      >
        <nav aria-label="서비스 정보">
          <ul className="flex flex-wrap gap-x-4 gap-y-2 break-keep">
            {FOOTER_LINK_KEYS.map((key) => (
              <li key={key}>
                <Link
                  to={SUPPORT_DESTINATIONS[key].to}
                  className={cn(LINK_CLASS, key === "privacy" && "font-semibold text-foreground")}
                >
                  {SUPPORT_DESTINATIONS[key].label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <BusinessInfoList />
        <p className="text-xs text-muted-foreground">
          © {new Date().getFullYear()} {SITE_NAME}
        </p>
      </div>
    </footer>
  );
}

const MAIL_ORDER_REPORT = describeMailOrderReport(BUSINESS_INFO.mailOrderReportNumber, BUSINESS_INFO.registrationNumber);

/** 값이 길어도(주소) 어절 단위로 접혀 390px에서 가로 스크롤을 만들지 않는다 — 그래서 값에 `whitespace-nowrap`을
 * 걸지 않는다. */
function BusinessInfoList() {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs break-keep text-muted-foreground">
      <BusinessInfoItem term="상호">{BUSINESS_INFO.name}</BusinessInfoItem>
      <BusinessInfoItem term="대표자">{BUSINESS_INFO.representative}</BusinessInfoItem>
      <BusinessInfoItem term="사업자등록번호">{BUSINESS_INFO.registrationNumber}</BusinessInfoItem>
      <BusinessInfoItem term="통신판매업">
        {MAIL_ORDER_REPORT.label}
        {MAIL_ORDER_REPORT.verifyUrl !== null && (
          <>
            {" "}
            <a href={MAIL_ORDER_REPORT.verifyUrl} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
              사업자정보 확인
            </a>
          </>
        )}
      </BusinessInfoItem>
      <BusinessInfoItem term="주소">{BUSINESS_INFO.address}</BusinessInfoItem>
      <BusinessInfoItem term="전화">{BUSINESS_INFO.phone}</BusinessInfoItem>
      <BusinessInfoItem term="이메일">{BUSINESS_INFO.email}</BusinessInfoItem>
      <BusinessInfoItem term="호스팅 제공자">
        {BUSINESS_INFO.hostingProviders.map(({ name, role }) => `${name}(${role})`).join(", ")}
      </BusinessInfoItem>
    </dl>
  );
}

function BusinessInfoItem({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex gap-1.5">
      <dt className="whitespace-nowrap">{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

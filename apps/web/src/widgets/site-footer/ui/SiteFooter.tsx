import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useRouterState } from "@tanstack/react-router";

import { CONTACT_EMAIL, SITE_NAME } from "@/shared/config/site";
import { SUPPORT_DESTINATIONS, type SupportDestinationKey } from "@/shared/config/supportDestinations";

const FOOTER_LINK_KEYS = ["about", "terms", "privacy", "notices", "inquiry-new"] as const satisfies readonly SupportDestinationKey[];

const LINK_CLASS =
  "whitespace-nowrap rounded-sm text-xs text-muted-foreground motion-safe:transition-colors hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * 문서 끝에 놓이는 정보 푸터. 고정하지 않는다 — 루트 레이아웃이 페이지 영역을 늘려 짧은 페이지에서는 뷰포트
 * 바닥에, 긴 페이지에서는 끝까지 스크롤해야 만난다.
 *
 * 강조는 `개인정보처리방침` 하나뿐이다 — 처리방침은 첫 화면에서 다른 링크와 구별돼 찾을 수 있어야 한다. 색은
 * `primary`가 아니라 밝기 천장(`text-foreground`)과 굵기로 올린다 — `primary`는 이 시스템의 유일한 강조색이다.
 *
 * 콘텐츠 상세화면의 `lg` 미만에서는 플레이 바가 바닥에 `fixed`로 붙고 이 푸터가 그 화면 문서의 마지막
 * 요소다. 그래서 바 높이(p-4 16px×2 + 버튼 48px ≈ 80px + safe-area)만큼의 아래 여백을 여기서 져야 마지막
 * 줄이 바에 가려지지 않는다. `lg`부터는 바가 본문 안 인라인으로 돌아가 보통 여백으로 되돌린다.
 */
export function SiteFooter() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const hasFixedPlayBarBelow = pathname.startsWith("/content/");

  return (
    <footer className="border-t border-border">
      <div
        className={cn(
          "mx-auto flex max-w-5xl flex-col gap-3 px-4 pt-6 sm:px-6",
          hasFixedPlayBarBelow ? "pb-[calc(6rem+env(safe-area-inset-bottom))] lg:pb-4-safe" : "pb-4-safe",
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
        <p className="text-xs text-muted-foreground">
          {SITE_NAME} · {CONTACT_EMAIL}
        </p>
        <p className="text-xs text-muted-foreground">
          © {new Date().getFullYear()} {SITE_NAME}
        </p>
      </div>
    </footer>
  );
}

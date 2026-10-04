import { useState, type ReactNode } from "react";

import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";

import { useAdminShortcuts } from "../model/useAdminShortcuts";
import { AdminSidebar } from "./AdminSidebar";
import { AdminTopBar } from "./AdminTopBar";
import { CommandPalette } from "./CommandPalette";
import { SkipLink } from "./SkipLink";

/**
 * 로그인 화면을 뺀 모든 화면의 뼈대. `lg` 이상은 사이드바 + 본문, 미만은 sticky 상단바 + 본문이고 둘은 CSS
 * (`lg:`)로만 갈린다 — 첫 렌더 깜빡임이 없다.
 *
 * - 스크롤 컨테이너는 window 하나다. 이 셸과 본문 래퍼에 overflow 를 걸지 않는다 — 상단바·사이드바의 sticky 가
 *   죽고, 라우터의 이동 시 맨 위 리셋도 window 기준이다.
 * - 본문 래퍼가 문서의 유일한 `<main>` 이다 — 화면은 `PageContainer`(div)로 폭·거터만 정하고 랜드마크를 따로 두지
 *   않는다. 건너뛰기 링크가 포커스를 줄 수 있게 `tabIndex={-1}` 이다.
 * - 빠른 이동 팔레트의 열림 상태를 여기서 든다 — 여는 자리가 셋(상단바 버튼·사이드바 버튼·단축키)이다.
 */
export function AdminShell({ children }: { children: ReactNode }) {
  const [isPaletteOpen, setIsPaletteOpen] = useState(false);
  const openPalette = () => setIsPaletteOpen(true);
  useAdminShortcuts({ isPaletteOpen, onPaletteOpenChange: setIsPaletteOpen });

  return (
    <>
      <SkipLink />
      <div className="flex min-h-dvh flex-col lg:flex-row">
        <AdminTopBar onOpenPalette={openPalette} />
        <AdminSidebar onOpenPalette={openPalette} />
        <main id={MAIN_CONTENT_ID} tabIndex={-1} className="min-w-0 flex-1 outline-none">
          {children}
        </main>
      </div>
      <CommandPalette open={isPaletteOpen} onOpenChange={setIsPaletteOpen} />
    </>
  );
}

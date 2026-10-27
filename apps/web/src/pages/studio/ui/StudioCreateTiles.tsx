import { Link, type LinkProps } from "@tanstack/react-router";
import { BookOpen, ImagePlus, UserRound, type LucideIcon } from "lucide-react";

import { NEW_DRAFT_SEGMENT } from "@/shared/config/newDraftSegment";

type CreateTile = { key: string; label: string; summary: string; Icon: LucideIcon; link: LinkProps };

/**
 * 새로 만들기 칸. 캐릭터·스토리는 유형 선택 화면을 거치지 않고 새 초안 빌더로 바로 간다 — 여기서 이미 고른 유형을 다시
 * 묻지 않으려고. 이미지 생성은 같은 탭에서 이미지 스튜디오를 연다(파라미터 없이 — 생성 탭).
 *
 * 채팅에서 소설을 시작하는 칸은 아직 없다. 막힌 방을 미리 알려 줄 채팅 선택 화면이 생길 때 그 화면과 함께 더한다.
 */
const CREATE_TILES: CreateTile[] = [
  {
    key: "character",
    label: "캐릭터",
    summary: "대화 상대를 만들어요",
    Icon: UserRound,
    link: { to: "/builder/$type/$draftId", params: { type: "character", draftId: NEW_DRAFT_SEGMENT } },
  },
  {
    key: "story",
    label: "스토리",
    summary: "인물과 전개를 짜요",
    Icon: BookOpen,
    link: { to: "/builder/$type/$draftId", params: { type: "story", draftId: NEW_DRAFT_SEGMENT } },
  },
  {
    key: "image",
    label: "이미지 생성",
    summary: "표지·장면 그림을 만들어요",
    Icon: ImagePlus,
    link: { to: "/studio/images" },
  },
];

/** 칸은 페이지 배경 위의 윤곽 상자라 hover 는 `bg-muted` 다(유형 선택 화면의 카드와 같은 레시피). 좁은 폭에선 세 칸이
 * 한 줄이라 설명을 빼고 아이콘을 이름 위에 둔다. */
export function StudioCreateTiles() {
  return (
    <ul className="grid grid-cols-3 gap-2 sm:gap-3">
      {CREATE_TILES.map(({ key, label, summary, Icon, link }) => (
        <li key={key} className="flex">
          <Link
            {...link}
            className="flex min-h-full flex-1 flex-col gap-1 rounded-xl border border-border bg-background p-3 outline-none motion-safe:transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px sm:p-4"
          >
            <span className="flex flex-col items-start gap-1.5 text-sm font-semibold break-keep text-foreground sm:flex-row sm:items-center sm:gap-2">
              <Icon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
              {label}
            </span>
            <span className="hidden text-xs break-keep text-muted-foreground sm:block">{summary}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

import { Link, type LinkProps } from "@tanstack/react-router";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { BookOpen, BookText, ImagePlus, UserRound, type LucideIcon } from "lucide-react";

import { NEW_DRAFT_SEGMENT } from "@/shared/config/newDraftSegment";

import { toCreateTileKeys, type CreateTileKey } from "../model/createTiles";

type CreateTile = { label: string; summary: string; Icon: LucideIcon; link: LinkProps };

/**
 * 새로 만들기 칸. 캐릭터·스토리는 유형 선택 화면을 거치지 않고 새 초안 빌더로 바로 간다 — 여기서 이미 고른 유형을 다시
 * 묻지 않으려고. 내 채팅으로 소설은 소설로 엮을 대화를 고르는 화면으로 간다 — 막힌 방은 거기서 이유와 함께 보인다. 이미지
 * 생성은 같은 탭에서 이미지 스튜디오를 연다(파라미터 없이 — 생성 탭).
 */
const CREATE_TILES: Record<CreateTileKey, CreateTile> = {
  character: {
    label: "캐릭터",
    summary: "대화 상대를 만들어요",
    Icon: UserRound,
    link: { to: "/builder/$type/$draftId", params: { type: "character", draftId: NEW_DRAFT_SEGMENT } },
  },
  story: {
    label: "스토리",
    summary: "인물과 전개를 짜요",
    Icon: BookOpen,
    link: { to: "/builder/$type/$draftId", params: { type: "story", draftId: NEW_DRAFT_SEGMENT } },
  },
  novel: {
    label: "내 채팅으로 소설",
    summary: "대화를 골라 소설로 엮어요",
    Icon: BookText,
    link: { to: "/studio/new-novel" },
  },
  image: {
    label: "이미지 생성",
    summary: "표지·장면 그림을 만들어요",
    Icon: ImagePlus,
    link: { to: "/studio/images" },
  },
};

/** 칸은 페이지 배경 위의 윤곽 상자라 hover 는 `bg-muted` 다(유형 선택 화면의 카드와 같은 레시피). 좁은 폭에선 칸이 좁아
 * 설명을 빼고 아이콘을 이름 위에 둔다 — 셋이면 한 줄, 넷이면 두 줄 두 칸(한 줄에 넷이면 칸이 좁아 "내 채팅으로
 * 소설"이 여러 줄로 접힌다). */
export function StudioCreateTiles({ isNovelAreaVisible }: { isNovelAreaVisible: boolean }) {
  const keys = toCreateTileKeys(isNovelAreaVisible);

  return (
    <ul className={cn("grid gap-2 sm:gap-3", keys.length === 4 ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-3")}>
      {keys.map((key) => {
        const { label, summary, Icon, link } = CREATE_TILES[key];
        return (
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
        );
      })}
    </ul>
  );
}

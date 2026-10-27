import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";

import type { WorkBundleSummary } from "@/entities/work";

type StudioBundleHeaderProps = {
  /** 화면 제목의 id — 화면이 바뀐 뒤 포커스를 받는 자리라 페이지가 정한다. */
  headingId: string;
  bundle: WorkBundleSummary;
  onAddWorks: () => void;
  onRename: () => void;
  onDelete: () => void;
};

/** 스튜디오 홈의 모든 작품 목록으로 돌아가는 글자 링크. 묶음만 빼고 나머지 조건은 그대로 둔다. 라벨을 "스튜디오"로
 * 두지 않는 이유: 같은 화면의 좌측 패널(드로어)에 같은 이름·같은 경로의 `스튜디오` 링크가 있어, 스크린리더에 같은 항목이
 * 두 번 읽힌다 — 돌아가는 곳(조건을 지킨 모든 작품 목록)을 이름으로 삼아 가른다. */
export function StudioBackLink() {
  return (
    <Link
      from="/studio/"
      to="/studio"
      search={(previous) => ({ ...previous, bundle: undefined })}
      className="-ml-1 inline-flex w-fit items-center gap-0.5 rounded-md px-1 text-sm font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10"
    >
      <ChevronLeft aria-hidden className="size-4" />
      모든 작품
    </Link>
  );
}

/**
 * 묶음 화면의 머리 — 묶음 이름(h1) · 나만 보는 정리라는 한 줄 · 작품 넣기 · 이름 바꾸기·지우기 메뉴.
 *
 * 작품 넣기는 윤곽 버튼이다. 이 화면에는 이어 만들기 카드가 없어 채움을 쓰면 화면의 유일한 밝은 덩어리가 되는데, 이 일이
 * 그만큼 무겁지 않다(채움은 대화상자 안의 실행 버튼만 진다).
 */
export function StudioBundleHeader({ headingId, bundle, onAddWorks, onRename, onDelete }: StudioBundleHeaderProps) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
          <h1
            id={headingId}
            tabIndex={-1}
            className="text-2xl font-bold tracking-tight text-balance break-keep text-foreground outline-none [overflow-wrap:anywhere]"
          >
            {bundle.name}
          </h1>
          <p className="text-sm text-muted-foreground">나만 보는 정리예요. 독자에게는 보이지 않아요.</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button type="button" variant="outline" className="pointer-coarse:h-10" onClick={onAddWorks}>
            <Plus aria-hidden />
            작품 넣기
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label="묶음 더보기"
                className="pointer-coarse:size-10"
              >
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-auto">
              <DropdownMenuItem onSelect={onRename}>
                <Pencil aria-hidden />
                이름 바꾸기
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2 aria-hidden />
                묶음 지우기
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
    </div>
  );
}

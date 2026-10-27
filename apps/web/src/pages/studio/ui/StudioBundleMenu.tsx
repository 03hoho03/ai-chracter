import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Link } from "@tanstack/react-router";
import { ChevronDown, FolderOpen, Plus } from "lucide-react";

import { useWorkBundlesQuery, WORK_BUNDLE_MAX_COUNT } from "@/entities/work";

type StudioBundleMenuProps = {
  /** "새 묶음 만들기" — 만들고 그 묶음 화면으로 옮기는 일은 페이지가 한다(이름 모달이 페이지에 붙어 있다). */
  onCreateBundle: () => void;
};

/**
 * 모든 작품 머리의 "묶음" 메뉴 — 내 묶음으로 가는 링크 목록과 새 묶음 만들기. 묶음은 나만 보는 정리라 스튜디오 안 여기에서만
 * 들어간다.
 *
 * 묶음 링크는 다른 조건(유형·상태·검색어)을 버리고 묶음만 싣는다 — 홈에서 걸어 둔 필터가 따라 들어가면 묶음이 비어 보인다.
 * 한도에 닿으면 "새 묶음 만들기"는 사라지지 않고 흐려지며 이유를 함께 읽힌다(`aria-disabled` — Radix 의 `disabled` 는
 * 키보드 순회에서 빠져 이유가 닿지 않는다).
 */
export function StudioBundleMenu({ onCreateBundle }: StudioBundleMenuProps) {
  const query = useWorkBundlesQuery();
  const bundles = query.data?.items ?? [];
  const isAtLimit = bundles.length >= WORK_BUNDLE_MAX_COUNT;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="shrink-0 pointer-coarse:h-10">
          <FolderOpen aria-hidden />
          묶음
          <ChevronDown aria-hidden className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto max-w-80 min-w-56">
        <BundleLinks query={query} />
        <DropdownMenuSeparator />
        <DropdownMenuItem
          aria-disabled={isAtLimit || query.isPending}
          onSelect={(event) => {
            if (isAtLimit || query.isPending) {
              event.preventDefault();
              return;
            }
            onCreateBundle();
          }}
          className="items-start"
        >
          <Plus aria-hidden className="mt-0.5" />
          <span className="flex flex-col gap-0.5">
            새 묶음 만들기
            {isAtLimit && (
              <span className="text-xs break-keep text-muted-foreground">
                묶음은 {WORK_BUNDLE_MAX_COUNT}개까지 만들 수 있어요
              </span>
            )}
          </span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** 묶음 링크 목록 자리 — 받는 중·실패·없음·목록 넷 중 하나. */
function BundleLinks({ query }: { query: ReturnType<typeof useWorkBundlesQuery> }) {
  const bundles = query.data?.items ?? [];

  if (query.isPending) {
    return <DropdownMenuLabel className="font-normal text-muted-foreground">불러오는 중…</DropdownMenuLabel>;
  }
  if (query.isError && bundles.length === 0) {
    return (
      <DropdownMenuItem
        onSelect={(event) => {
          event.preventDefault();
          void query.refetch();
        }}
      >
        묶음을 불러오지 못했어요 · 다시 시도
      </DropdownMenuItem>
    );
  }
  if (bundles.length === 0) {
    return (
      <DropdownMenuLabel className="max-w-64 font-normal break-keep text-muted-foreground">
        아직 묶음이 없어요. 작품을 묶어 나만 보는 정리를 만들어 보세요.
      </DropdownMenuLabel>
    );
  }
  return bundles.map((bundle) => (
    <DropdownMenuItem key={bundle.id} asChild>
      <Link to="/studio" search={{ bundle: bundle.id }} className="justify-between gap-4">
        <span className="min-w-0 truncate">{bundle.name}</span>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{bundle.itemCount}개</span>
      </Link>
    </DropdownMenuItem>
  ));
}

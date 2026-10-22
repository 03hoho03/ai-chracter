import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { BookImage, ChevronDown, Images, Upload, type LucideIcon } from "lucide-react";
import { useState } from "react";

import type { IllustrationPlacement, IllustrationSource } from "../model/boardIllustrations";

type IllustrationSourceMenuProps = {
  /** 트리거 글자("그림 붙이기"·"바꾸기"). 진행 중이면 `pendingLabel` 이 대신한다. */
  label: string;
  pendingLabel: string | undefined;
  icon: LucideIcon;
  variant: "outline" | "ghost";
  /** 막혔으면 메뉴가 열리지 않는다(`aria-disabled` — 누른 버튼의 포커스를 지킨다). */
  isBlocked: boolean;
  describedBy: string | undefined;
  /** 붙이기면 놓을 자리(고른 범위 뒤·앞)를 메뉴 머리에서 고른다. 바꾸기는 자리가 그대로라 없다. */
  hasPlacement: boolean;
  onPick: (source: IllustrationSource, placement: IllustrationPlacement) => void;
};

const SOURCES: { source: IllustrationSource; label: string; icon: LucideIcon }[] = [
  { source: "upload", label: "기기에서 올리기", icon: Upload },
  { source: "generated", label: "내 이미지에서", icon: Images },
  { source: "original", label: "원작 이미지에서", icon: BookImage },
];

/**
 * 그림의 출처 셋을 고르는 메뉴. 출처를 고르면 그 출처의 창(파일 고르기 → 자르기, 내 이미지, 원작 그림)이 열린다 — 창 하나가
 * 일 하나다. 붙이기면 메뉴 머리에 놓을 자리 라디오가 있고 기본은 고른 범위 뒤다. 라디오를 골라도 메뉴는 닫히지 않는다(이어서
 * 출처를 고른다).
 */
export function IllustrationSourceMenu({
  label,
  pendingLabel,
  icon: Icon,
  variant,
  isBlocked,
  describedBy,
  hasPlacement,
  onPick,
}: IllustrationSourceMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [placement, setPlacement] = useState<IllustrationPlacement>("after");

  return (
    <DropdownMenu open={isOpen} onOpenChange={(next) => setIsOpen(next && !isBlocked)}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant={variant}
          size="sm"
          aria-disabled={isBlocked}
          aria-describedby={describedBy}
          className="aria-disabled:opacity-65 aria-expanded:bg-secondary"
        >
          <Icon aria-hidden />
          {pendingLabel ?? label}
          <ChevronDown aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-auto max-w-72">
        {hasPlacement && (
          <>
            <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">놓을 자리</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={placement}
              onValueChange={(value) => setPlacement(value === "before" ? "before" : "after")}
            >
              <DropdownMenuRadioItem value="after" onSelect={(event) => event.preventDefault()}>
                고른 문단 뒤
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="before" onSelect={(event) => event.preventDefault()}>
                고른 문단 앞
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">그림 고르기</DropdownMenuLabel>
          </>
        )}
        {SOURCES.map(({ source, label: sourceLabel, icon: SourceIcon }) => (
          <DropdownMenuItem key={source} onSelect={() => onPick(source, placement)}>
            <SourceIcon aria-hidden />
            {sourceLabel}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

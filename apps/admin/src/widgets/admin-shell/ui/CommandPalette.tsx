import { useNavigate } from "@tanstack/react-router";
import { BookOpen, UserSearch, Users } from "lucide-react";
import { useRef, useState } from "react";

import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  Kbd,
} from "@/shared/ui/Command";

import { ADMIN_NAV_GROUPS } from "../config/nav";
import { PALETTE_SHORTCUT } from "../model/useAdminShortcuts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type CommandPaletteProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * 빠른 이동 팔레트. 화면 11개(내비와 같은 그룹·아이콘), 붙여 넣은 UUID 의 작품·유저 상세, 그 밖의 글자로 유저 목록 검색
 * (이메일·닉네임 일부 일치)을 고른다. 모든 이동이 라우터를 거치므로 편집 화면의 이탈 확인이 그대로 걸린다.
 *
 * 포커스: 연 자리(단축키면 그때 포커스가 있던 곳)를 기억했다가 Esc·바깥 누르기로 닫히면 그리로 돌려준다 — 트리거 없이
 * 열리는 대화상자라 그냥 두면 `<body>` 로 떨어진다. 항목으로 이동하면 새 화면 본문으로 보낸다(드로어와 같은 규칙).
 */
export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const returnFocusRef = useRef<Element | null>(null);
  const isClosingForNavigationRef = useRef(false);

  function go(navigateTo: () => Promise<void>) {
    isClosingForNavigationRef.current = true;
    onOpenChange(false);
    void navigateTo();
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="빠른 이동"
      description="화면 이름으로 이동하거나, 작품·유저 ID 또는 이메일로 찾아요."
      onOpenAutoFocus={() => {
        // 포커스 범위가 입력칸으로 옮기기 직전이라 아직 연 자리에 포커스가 있다.
        returnFocusRef.current = document.activeElement;
      }}
      onCloseAutoFocus={(event) => {
        event.preventDefault();
        const target = returnFocusRef.current;
        returnFocusRef.current = null;
        if (isClosingForNavigationRef.current) {
          isClosingForNavigationRef.current = false;
          // 이동이 편집 화면의 이탈 확인으로 막혔으면 그 확인 창이 먼저 포커스를 가져갔다 — 빼앗지 않는다.
          const active = document.activeElement;
          if (active !== null && active !== document.body && active.isConnected) return;
          document.getElementById(MAIN_CONTENT_ID)?.focus();
          return;
        }
        if (target instanceof HTMLElement && target !== document.body && target.isConnected) target.focus();
      }}
    >
      {/* 대화상자가 닫히면 이 안이 언마운트돼 다음에 열 때 검색어가 비어 있다. */}
      <PaletteBody onGo={go} />
    </CommandDialog>
  );
}

type PaletteBodyProps = {
  onGo: (navigateTo: () => Promise<void>) => void;
};

function PaletteBody({ onGo }: PaletteBodyProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const term = query.trim();
  const isUuid = UUID_PATTERN.test(term);
  const normalizedTerm = term.toLowerCase();
  const navGroups = ADMIN_NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter(
      (item) =>
        normalizedTerm === "" ||
        item.label.toLowerCase().includes(normalizedTerm) ||
        group.label.toLowerCase().includes(normalizedTerm),
    ),
  })).filter((group) => group.items.length > 0);

  return (
    <>
      <CommandInput value={query} onValueChange={setQuery} placeholder="화면 이름, ID, 이메일" />
      <CommandList>
        <CommandEmpty>맞는 항목이 없어요.</CommandEmpty>

        {isUuid && (
          <CommandGroup heading="ID로 이동">
            <CommandItem
              value="id:content"
              onSelect={() => onGo(() => navigate({ to: "/contents/$contentId", params: { contentId: term } }))}
            >
              <BookOpen aria-hidden />
              작품 상세 열기
            </CommandItem>
            <CommandItem
              value="id:user"
              onSelect={() => onGo(() => navigate({ to: "/users/$userId", params: { userId: term } }))}
            >
              <Users aria-hidden />
              유저 상세 열기
            </CommandItem>
          </CommandGroup>
        )}

        {navGroups.map((group) => (
          <CommandGroup key={group.label} heading={group.label}>
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <CommandItem key={item.to} value={`nav:${item.to}`} onSelect={() => onGo(() => navigate({ to: item.to }))}>
                  <Icon aria-hidden />
                  {item.label}
                </CommandItem>
              );
            })}
          </CommandGroup>
        ))}

        {term !== "" && !isUuid && (
          <CommandGroup heading="유저 찾기">
            <CommandItem value="search:user" onSelect={() => onGo(() => navigate({ to: "/users", search: { q: term } }))}>
              <UserSearch aria-hidden />
              <span className="min-w-0 truncate">‘{term}’ 이메일·닉네임으로 유저 찾기</span>
            </CommandItem>
          </CommandGroup>
        )}
      </CommandList>

      <ShortcutHints />
    </>
  );
}

/** 팔레트 바닥의 단축키 목록. 어드민 단축키는 이것이 전부다. */
function ShortcutHints() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border px-3 py-2 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        <Kbd>{PALETTE_SHORTCUT.label}</Kbd>
        열기·닫기
      </span>
      <span className="inline-flex items-center gap-1">
        <Kbd>/</Kbd>
        목록 검색칸으로
      </span>
      <span className="inline-flex items-center gap-1">
        <Kbd>↑</Kbd>
        <Kbd>↓</Kbd>
        고르기
      </span>
      <span className="inline-flex items-center gap-1">
        <Kbd>Enter</Kbd>
        이동
      </span>
      <span className="inline-flex items-center gap-1">
        <Kbd>Esc</Kbd>
        닫기
      </span>
    </div>
  );
}

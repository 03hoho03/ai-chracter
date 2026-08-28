import { useMemo } from "react";

import type { Shortcut } from "@/entities/chat-room";
import { filterShortcuts } from "../model/filterShortcuts";

type ShortcutAutocompleteProps = {
  shortcuts: Shortcut[];
  query: string;
  onSelect: (shortcut: Shortcut) => void;
}

// techspec-chat-story.md §4 — 입력창이 '/'로 시작할 때만 부모가 이 컴포넌트를 마운트한다.
// 항목 선택은 확인 단계 없이 즉시 전송으로 이어진다(호출부 책임).
export function ShortcutAutocomplete({ shortcuts, query, onSelect }: ShortcutAutocompleteProps) {
  const matches = useMemo(() => filterShortcuts(query, shortcuts), [query, shortcuts]);

  if (shortcuts.length === 0) return null;

  return (
    <div
      role="listbox"
      aria-label="단축어 자동완성"
      className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:duration-100 absolute inset-x-0 bottom-full z-50 mb-2 max-h-60 overflow-y-auto rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10"
    >
      {matches.length === 0 ? (
        <p className="px-2.5 py-2 text-xs text-muted-foreground">일치하는 단축어가 없어요</p>
      ) : (
        matches.map((shortcut) => (
          <button
            key={shortcut.id}
            type="button"
            role="option"
            aria-selected={false}
            onClick={() => onSelect(shortcut)}
            className="flex w-full flex-col gap-0.5 rounded-md px-2.5 py-2 text-left outline-hidden hover:bg-accent focus-visible:inset-ring-1 focus-visible:inset-ring-ring focus-visible:bg-accent"
          >
            <span className="text-sm font-medium text-foreground">{shortcut.name}</span>
            <span className="line-clamp-1 text-xs text-muted-foreground">{shortcut.description}</span>
          </button>
        ))
      )}
    </div>
  );
}

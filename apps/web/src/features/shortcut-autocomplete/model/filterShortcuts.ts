import type { Shortcut } from "@/entities/chat-room";

// techspec-chat-story.md §4 — query는 '/' 뒤의 나머지 텍스트. 비어있으면 전체 목록을 그대로 후보로 보여준다.
export function filterShortcuts(query: string, shortcuts: Shortcut[]): Shortcut[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return shortcuts;
  return shortcuts.filter((shortcut) => shortcut.name.toLowerCase().includes(needle));
}

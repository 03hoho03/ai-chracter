import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { BookOpen, UserRound } from "lucide-react";

import { contentTypeToggleAtom, type ContentTypeToggleValue } from "../../../shared/model/content-type-toggle";

function isContentTypeToggleValue(value: string): value is ContentTypeToggleValue {
  return value === "character" || value === "story";
}

/** techspec-global-nav-profile.md §1.1 — 클릭 시 전역 atom을 갱신하고 홈으로 이동한다(FR-10). */
export function ContentTypeToggle() {
  const [contentType, setContentType] = useAtom(contentTypeToggleAtom);
  const navigate = useNavigate();

  const handleValueChange = (value: string) => {
    // Radix ToggleGroup(type="single")은 이미 선택된 항목을 다시 누르면 빈 문자열을 emit한다 — 그 경우 무시해
    // 토글이 항상 정확히 하나만 선택된 상태를 유지하게 한다.
    if (!isContentTypeToggleValue(value)) return;
    setContentType(value);
    void navigate({ to: "/" });
  };

  return (
    <ToggleGroup
      type="single"
      variant="outline"
      value={contentType}
      onValueChange={handleValueChange}
      aria-label="콘텐츠 유형 전환"
      className="shrink-0"
    >
      <ToggleGroupItem value="character" aria-label="캐릭터">
        <UserRound aria-hidden />
        <span className="hidden sm:inline">캐릭터</span>
      </ToggleGroupItem>
      <ToggleGroupItem value="story" aria-label="스토리">
        <BookOpen aria-hidden />
        <span className="hidden sm:inline">스토리</span>
      </ToggleGroupItem>
    </ToggleGroup>
  );
}

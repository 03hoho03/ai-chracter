import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";

import { contentTypeToggleAtom, isContentType } from "@/entities/content";

/** techspec-global-nav-profile.md §1.1 — 클릭 시 전역 atom을 갱신하고 홈으로 이동한다(FR-10).
 *
 * `variant`(MR-14) — 헤더는 기본값 `"tab"`(라벨만 있는 라우트 전환 탭), 좌측 드로어는 `"outline"`
 * (가로 pill 쌍, `DESIGN.md` §Toggles 감사 테스트: 라벨 3자짜리 버튼 크기라 `list`가 아니라 기본 채움).
 * 재클릭 `""` emit 가드와 `navigate({ to: "/" })`는 이 컴포넌트 한 곳에만 둔다 — 헤더·드로어 두 인스턴스가
 * 복제하면 한쪽이 조용히 새는 게 이 저장소의 실패 모드다("17곳 중 2곳만 맞았다"). */
export function ContentTypeToggle({ variant = "tab" }: { variant?: "tab" | "outline" } = {}) {
  const [contentType, setContentType] = useAtom(contentTypeToggleAtom);
  const navigate = useNavigate();

  const handleValueChange = (value: string) => {
    // Radix ToggleGroup(type="single")은 이미 선택된 항목을 다시 누르면 빈 문자열을 emit한다 — 그 경우 무시해
    // 토글이 항상 정확히 하나만 선택된 상태를 유지하게 한다.
    if (!isContentType(value)) return;
    setContentType(value);
    void navigate({ to: "/" });
  };

  return (
    <ToggleGroup
      type="single"
      variant={variant}
      value={contentType}
      onValueChange={handleValueChange}
      aria-label="콘텐츠 유형 전환"
      className="shrink-0"
    >
      {/* 라벨이 상시 노출되므로 접근가능 이름은 텍스트 노드에서 계산된다 — `aria-label="캐릭터"/"스토리"`는
          죽은 prop이라 제거했다(main-refact-goal-prompt.md MR-2). */}
      <ToggleGroupItem value="character">캐릭터</ToggleGroupItem>
      <ToggleGroupItem value="story">스토리</ToggleGroupItem>
    </ToggleGroup>
  );
}

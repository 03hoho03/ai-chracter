import { Button } from "@ai-character-chat/ui/components/button";
import { Eye, Save } from "lucide-react";

type BuilderTopBarActionsProps = {
  /** 발행 요청(onValid 경로)이 진행 중인지 — 발행 버튼을 잠그고 라벨을 바꾼다.
   *
   * FORM-07("중복 제출 방지는 `form.formState.isSubmitting`")을 의도적으로 벗어난다 — `isSubmitting`은
   * 검증 구간까지 포함해 true가 되는데, 이 버튼은 네이티브 `disabled`라 유효성 실패 때마다 포커스가
   * body로 떨어진다. 그래서 발행 성공 경로(onValid)에서만 켜지는 로컬 state를 쓴다
   * (fe-convention-refactor-progress.md V-3). */
  isPublishing: boolean;
  onPreview: () => void;
  onSaveNow: () => void;
  onPublish: () => void;
};

/**
 * `BuilderTopBar`의 `actions` 슬롯에 들어가는 세 버튼(미리보기·임시저장·발행). 두 셸이 글자 단위로
 * 같은 JSX를 들고 있던 것을 모았다(fe-convention-refactor-goal-prompt.md R-3) — 셸마다 다른 제목은
 * 원래부터 `BuilderTopBar`의 `title` prop이라 여기 오지 않는다.
 *
 * [미리보기]는 lg 이상에서 프리뷰 열이 항상 보이므로 `lg:hidden`이고(D-1), 폭이 좁을 때 미리보기·임시저장
 * 두 버튼은 라벨을 숨기고 아이콘만 남긴다(`hidden sm:inline`, `BuilderTopBar` 주석의 선례) — 발행은 아이콘이 없어
 * 라벨을 항상 노출한다.
 */
export function BuilderTopBarActions({
  isPublishing,
  onPreview,
  onSaveNow,
  onPublish,
}: BuilderTopBarActionsProps) {
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label="미리보기"
        className="lg:hidden"
        onClick={onPreview}
      >
        <Eye aria-hidden className="size-3.5" />
        <span className="hidden sm:inline">미리보기</span>
      </Button>
      <Button type="button" variant="outline" size="sm" aria-label="임시저장" onClick={onSaveNow}>
        <Save aria-hidden className="size-3.5" />
        <span className="hidden sm:inline">임시저장</span>
      </Button>
      <Button size="sm" disabled={isPublishing} onClick={onPublish}>
        {isPublishing ? "발행 중..." : "발행"}
      </Button>
    </>
  );
}

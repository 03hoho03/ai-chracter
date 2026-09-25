import { Button } from "@ai-character-chat/ui/components/button";
import { Eye, Save, X } from "lucide-react";

type BuilderTopBarActionsProps = {
  /** 발행 요청(onValid 경로)이 진행 중인지 — 발행 버튼을 잠그고 라벨을 바꾼다.
   *
   * 폼 컨벤션("중복 제출 방지는 `form.formState.isSubmitting`")을 의도적으로 벗어난다 — `isSubmitting`은
   * 검증 구간까지 포함해 true가 되는데, 이 버튼은 네이티브 `disabled`라 유효성 실패 때마다 포커스가
   * body로 떨어진다. 그래서 발행 성공 경로(onValid)에서만 켜지는 로컬 state를 쓴다. */
  isPublishing: boolean;
  /** [미리보기] 버튼을 토글로 만드는 데 필요한 표시용 상태.
   * 열고 닫는 로직(state 갱신)은 두 셸이 이미 갖고 있어 여기서는 아이콘·라벨·aria-expanded만 이 값을 따른다. */
  isPreviewOpen: boolean;
  onPreview: () => void;
  onSaveNow: () => void;
  onPublish: () => void;
};

/**
 * `BuilderTopBar`의 `actions` 슬롯에 들어가는 세 버튼(미리보기·임시저장·발행). 두 셸이 글자 단위로
 * 같은 JSX를 들고 있던 것을 모았다 — 셸마다 다른 제목은
 * 원래부터 `BuilderTopBar`의 `title` prop이라 여기 오지 않는다.
 *
 * [미리보기]는 lg 이상에서 프리뷰 열이 항상 보이므로 `lg:hidden`이고, 폭이 좁을 때 미리보기·임시저장
 * 두 버튼은 라벨을 숨기고 아이콘만 남긴다(`hidden sm:inline`, `BuilderTopBar` 주석의 선례) — 발행은 아이콘이 없어
 * 라벨을 항상 노출한다.
 */
export function BuilderTopBarActions({
  isPublishing,
  isPreviewOpen,
  onPreview,
  onSaveNow,
  onPublish,
}: BuilderTopBarActionsProps) {
  return (
    <>
      {/* 열림 상태에 따라 아이콘·라벨·aria-expanded가 바뀐다. 실제 열기/닫기 토글 로직은
          onPreview 쪽(셸)이 쥐고 있고, 이 버튼은 그 상태를 표시만 한다. `X`는 `SearchInlineExpand`가
          펼침 버튼을 닫기로 바꿀 때 쓰는 것과 같은 어휘다(검색 닫기 패턴 재사용). */}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={isPreviewOpen ? "미리보기 닫기" : "미리보기"}
        aria-expanded={isPreviewOpen}
        className="lg:hidden"
        onClick={onPreview}
      >
        {isPreviewOpen ? (
          <X aria-hidden className="size-3.5" />
        ) : (
          <Eye aria-hidden className="size-3.5" />
        )}
        <span className="hidden sm:inline">{isPreviewOpen ? "닫기" : "미리보기"}</span>
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

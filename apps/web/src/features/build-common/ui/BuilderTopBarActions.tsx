import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { onlineManager } from "@tanstack/react-query";
import { BookOpen, Check, CloudOff, Eye, Loader2, Save, TriangleAlert, X } from "lucide-react";
import { useSyncExternalStore, type ReactNode } from "react";

import type { CreationGuidePath } from "@/shared/config/creationGuide";

import type { AutosaveStatus, AutosaveStatusStore } from "../model/autosaveStatus";

type BuilderTopBarActionsProps = {
  /** 이 빌더의 작성 가이드 경로. 스토리·캐릭터 빌더가 각자 자기 가이드를 가리킨다. */
  guidePath: CreationGuidePath;
  /** 발행 요청(onValid 경로)이 진행 중인지 — 발행 버튼을 잠그고 라벨을 바꾼다.
   *
   * 폼 컨벤션("중복 제출 방지는 `form.formState.isSubmitting`")을 의도적으로 벗어난다 — `isSubmitting`은
   * 검증 구간까지 포함해 true가 되는데, 이 버튼은 네이티브 `disabled`라 유효성 실패 때마다 포커스가
   * body로 떨어진다. 그래서 발행 성공 경로(onValid)에서만 켜지는 로컬 state를 쓴다. */
  isPublishing: boolean;
  /** [미리보기] 버튼을 토글로 만드는 데 필요한 표시용 상태.
   * 열고 닫는 로직(state 갱신)은 두 셸이 이미 갖고 있어 여기서는 아이콘·라벨·aria-expanded만 이 값을 따른다. */
  isPreviewOpen: boolean;
  /** 닫힌 [미리보기] 버튼의 이름. lg 미만에서 이 버튼이 여는 화면이 탭에 따라 대화가 아닐 수 있어(스토리 빌더
   * 미디어 북 탭은 배치표) 셸이 그 화면의 머리와 같은 말을 넘긴다. 열렸을 때는 "{이름} 닫기"다. */
  previewLabel?: string;
  /** 닫힌 [미리보기] 버튼의 아이콘(`size-3.5`, `aria-hidden`). 이름을 바꿀 때 함께 넘긴다. */
  previewIcon?: ReactNode;
  /** 저장 상태(`useDraftPersistence` 의 `saveStatus`). 임시저장 버튼이 아이콘과 접근 이름으로 그린다. */
  saveStatus: AutosaveStatusStore;
  onPreview: () => void;
  onSaveNow: () => void;
  onPublish: () => void;
};

/**
 * `BuilderTopBar`의 `actions` 슬롯에 들어가는 작성 가이드 링크와 세 버튼(미리보기·임시저장·발행). 두 셸이 글자 단위로
 * 같은 JSX를 들고 있던 것을 모았다 — 셸마다 다른 제목은
 * 원래부터 `BuilderTopBar`의 `title` prop이라 여기 오지 않는다.
 *
 * [미리보기]는 lg 이상에서 프리뷰 열이 항상 보이므로 `lg:hidden`이고, 폭이 좁을 때 작성 가이드·미리보기·
 * 임시저장 세 컨트롤은 라벨을 숨기고 아이콘만 남긴다(`hidden sm:inline`, `BuilderTopBar` 주석의 선례) — 발행은
 * 아이콘이 없어 라벨을 항상 노출한다.
 */
export function BuilderTopBarActions({
  guidePath,
  isPublishing,
  isPreviewOpen,
  previewLabel = "미리보기",
  previewIcon = <Eye aria-hidden className="size-3.5" />,
  saveStatus,
  onPreview,
  onSaveNow,
  onPublish,
}: BuilderTopBarActionsProps) {
  return (
    <>
      {/* 작성 가이드는 새 탭으로 연다 — 같은 탭에서 이동하면 쓰던 폼을 떠나게 된다. 라우터 `Link` 가 아니라
          평범한 `<a>` 인 이유도 그것이다(새 탭은 앱을 처음부터 다시 띄운다). 폼 액션이 아니라 이동이라
          보더 없는 ghost 로 두어 옆의 임시저장·미리보기와 형태로 가른다. */}
      <Button asChild variant="ghost" size="sm" className={TOUCH_TARGET_CLASSNAME}>
        <a href={guidePath} target="_blank" rel="noopener noreferrer" aria-label="작성 가이드 (새 탭에서 열림)">
          <BookOpen aria-hidden className="size-3.5" />
          <span className="hidden sm:inline">작성 가이드</span>
        </a>
      </Button>
      {/* 열림 상태에 따라 아이콘·라벨·aria-expanded가 바뀐다. 실제 열기/닫기 토글 로직은
          onPreview 쪽(셸)이 쥐고 있고, 이 버튼은 그 상태를 표시만 한다. `X`는 `SearchInlineExpand`가
          펼침 버튼을 닫기로 바꿀 때 쓰는 것과 같은 어휘다(검색 닫기 패턴 재사용). */}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={isPreviewOpen ? `${previewLabel} 닫기` : previewLabel}
        aria-expanded={isPreviewOpen}
        className={cn("lg:hidden", TOUCH_TARGET_CLASSNAME)}
        onClick={onPreview}
      >
        {isPreviewOpen ? <X aria-hidden className="size-3.5" /> : previewIcon}
        <span className="hidden sm:inline">{isPreviewOpen ? "닫기" : previewLabel}</span>
      </Button>
      <SaveNowButton saveStatus={saveStatus} onSaveNow={onSaveNow} />
      <Button size="sm" disabled={isPublishing} className={TOUCH_TARGET_CLASSNAME} onClick={onPublish}>
        {isPublishing ? "발행 중..." : "발행"}
      </Button>
    </>
  );
}

/** 손가락 포인터에서 상단바 버튼을 40px 로 올린다. 좁은 화면에서는 라벨이 숨어 아이콘만 남으므로 폭도 40px 를 채운다. 상단바(56px)
 * 안에 들어가고, 마우스 포인터의 32px 는 그대로다. */
const TOUCH_TARGET_CLASSNAME = "pointer-coarse:h-10 pointer-coarse:min-w-10";

/** 상태별 아이콘과 접근 이름 뒤에 붙는 말. 오프라인은 저장 상태가 아니라 연결 상태라 여기 없고 `SaveNowButton` 이 덮어쓴다. */
const SAVE_STATUS_VIEW: Record<AutosaveStatus, { icon: ReactNode; text?: string }> = {
  idle: { icon: <Save aria-hidden className="size-3.5" /> },
  // 회전은 진행 표시라 `motion-safe:` 로 가두지 않는다 — 멈추면 저장이 멈춘 것으로 읽힌다.
  pending: { icon: <Loader2 aria-hidden className="size-3.5 animate-spin" />, text: "저장 대기 중" },
  saving: { icon: <Loader2 aria-hidden className="size-3.5 animate-spin" />, text: "저장 중" },
  saved: { icon: <Check aria-hidden className="size-3.5" />, text: "저장됨" },
  failed: {
    icon: <TriangleAlert aria-hidden className="size-3.5 text-destructive-text" />,
    text: "저장 실패, 눌러서 다시 시도",
  },
};

function subscribeOnline(listener: () => void) {
  return onlineManager.subscribe(listener);
}

const OFFLINE_VIEW = {
  icon: <CloudOff aria-hidden className="size-3.5" />,
  text: "연결 끊김, 연결되면 저장돼요",
};

/**
 * 임시저장 버튼이 자동저장 상태도 보인다 — 아이콘과 접근 이름("임시저장 · 저장됨")만 바뀌고 폭은 그대로다. 390px 상단바에는 상태
 * 글자를 더 놓을 폭이 없다. 실패면 이 버튼이 곧 다시 시도다(누르면 임시저장이 지금 값을 보낸다).
 *
 * 저장 상태는 이 버튼만 구독한다(셸은 다시 그리지 않는다). 오프라인은 TanStack 의 `onlineManager` 를 따른다 — 그 판단으로
 * 저장 요청이 멈추고 연결이 돌아오면 다시 나가므로, 같은 판단을 보여야 버튼이 실제 저장과 어긋나지 않는다.
 *
 * 보조기기에는 연결이 끊겼을 때만 상태 영역으로 알린다. 입력을 멈출 때마다 "저장됨"을 읽으면 소음이고, 저장 실패는 실패 토스트가
 * 이미 알린다(자동저장 실패 토스트는 닫을 때까지 남는다).
 */
function SaveNowButton({ saveStatus, onSaveNow }: { saveStatus: AutosaveStatusStore; onSaveNow: () => void }) {
  const status = useSyncExternalStore(saveStatus.subscribe, saveStatus.getSnapshot, saveStatus.getSnapshot);
  const isOnline = useSyncExternalStore(subscribeOnline, () => onlineManager.isOnline(), () => true);
  const view = isOnline ? SAVE_STATUS_VIEW[status] : OFFLINE_VIEW;
  const label = view.text ? `임시저장 · ${view.text}` : "임시저장";

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={label}
        className={TOUCH_TARGET_CLASSNAME}
        onClick={onSaveNow}
      >
        {view.icon}
        <span className="hidden sm:inline">임시저장</span>
      </Button>
      <span role="status" className="sr-only">
        {isOnline ? "" : "연결이 끊겼어요. 연결되면 저장돼요."}
      </span>
    </>
  );
}

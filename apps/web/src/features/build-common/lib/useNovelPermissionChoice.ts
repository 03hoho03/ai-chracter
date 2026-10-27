import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { contentVersionsQueryOptions, DEFAULT_NOVEL_PERMISSION, type NovelPermission } from "@/entities/content";

import { NOVEL_PERMISSION_PATH, needsNovelPermissionChoice, novelPermissionPublishValue } from "../model/novelPermissionChoice";

/** 공개 준비 탭이 허락 칸과 파생 소설 스위치를 그리는 데 쓰는 값. */
export type NovelPermissionChoiceView = {
  /** 세 줄을 모두 끈 "아직 고르지 않음" 그림인가. */
  isUnchosen: boolean;
  /** 발행이 이 칸 때문에 막혔는가(안내 문장을 오류로 바꾼다). */
  isBlocked: boolean;
  /** 작가가 세 줄 가운데 하나를 눌렀다. */
  onChoose: () => void;
  /** 발행 이력이 있다고 확인된 작품의 id. 그때만 "저장 즉시 적용" 안내와 파생 소설 스위치를 그린다. */
  publishedContentId: string | undefined;
};

/**
 * 첫 발행 전 소설 만들기 허락 고르기. "골랐는가"는 폼 값이 아니라 이 화면의 상태다 — 폼 값을 비우면 자동저장이 그 빈 값(또는 기본값)을
 * 서버에 덮어쓰고, 그림만 비우면 저장 경로는 그대로다. 그래서 새로고침하면 고른 기록은 사라지고, 저장값이 "허용 안 함"이면 다시 묻는다.
 *
 * 발행 이력은 그림에는 화면에 붙은 조회를, 발행을 누를 때는 서버에서 다시 읽은 값을 쓴다(다른 탭에서 방금 발행했을 수 있다). 조회가
 * 끝나기 전에는 "아직 고르지 않음"을 그리지 않는다 — 발행작에 그 그림이 깜빡이지 않게. 이 화면에서 새로 만든 초안은 이력이 0 이다.
 */
export function useNovelPermissionChoice({
  draftId,
  savedPermission: initialSavedPermission,
  hasAttemptedPublish,
}: {
  draftId: string | undefined;
  /** 열 때 서버에 저장돼 있던 값. 없으면(새 초안) 폼과 같은 기본값이다. */
  savedPermission: NovelPermission | undefined;
  /** 발행을 한 번이라도 눌렀는가(확인 목록이 서 있는가). */
  hasAttemptedPublish: boolean;
}) {
  const queryClient = useQueryClient();
  // 열 때의 값으로 고정한다 — 이 화면의 자동저장이 바꾼 값은 이 화면에서 고른 것이라 `chosen` 이 따로 말한다.
  const [savedPermission] = useState(initialSavedPermission ?? DEFAULT_NOVEL_PERMISSION);
  const [isNewDraft] = useState(draftId === undefined);
  const [chosen, setChosen] = useState(false);
  const [alreadyAsked, setAlreadyAsked] = useState(false);
  const versionsQuery = useQuery({
    ...contentVersionsQueryOptions(draftId ?? ""),
    enabled: !isNewDraft && draftId !== undefined,
  });
  const publishedCount = isNewDraft ? 0 : versionsQuery.data?.length;
  const state = { publishedCount, savedPermission, chosen, alreadyAsked };
  const needsChoice = needsNovelPermissionChoice(state);
  // 이력을 모르는 동안은 발행을 눌러 본 뒤에만 그린다. 막은 뒤로는 막힘과 그림이 같은 판정이다 — 그림이 고른 줄을 켜 둔 채 막으면
  // 그 줄을 다시 눌러도 Radix 가 "" 를 보내 고를 길이 없다.
  const isUnchosen = needsChoice && (publishedCount === 0 || hasAttemptedPublish || alreadyAsked);
  const isBlocked = isUnchosen && (hasAttemptedPublish || alreadyAsked);

  /** 발행을 누를 때 이력을 다시 읽어 막아야 하는지 본다. 조회가 실패하면 이력 없음으로 본다(`needsNovelPermissionChoice`). 막으면
   * 고를 때까지 묻는 상태로 남긴다. */
  async function checkBeforePublish(): Promise<{ blocked: boolean; publishedCount: number | undefined }> {
    const count =
      isNewDraft || draftId === undefined
        ? 0
        : await queryClient.fetchQuery({ ...contentVersionsQueryOptions(draftId), retry: false }).then(
            (versions) => versions.length,
            () => undefined,
          );
    const blocked = needsNovelPermissionChoice({ ...state, publishedCount: count });
    if (blocked) setAlreadyAsked(true);
    return { blocked, publishedCount: count };
  }

  const view: NovelPermissionChoiceView = {
    isUnchosen,
    isBlocked,
    onChoose: () => setChosen(true),
    publishedContentId: draftId !== undefined && publishedCount !== undefined && publishedCount > 0 ? draftId : undefined,
  };

  return {
    view,
    /** 확인 목록·탭 오류 표시에 더할 경로. 막혀 있을 때만 이 칸 하나다. */
    issuePaths: isBlocked ? [NOVEL_PERMISSION_PATH] : [],
    /** 지금 화면 값으로 고르라고 해야 하는가 — 클라 검사에서 막힌 발행이 확인 목록에 이 칸을 함께 올릴지 정한다. */
    needsChoice,
    checkBeforePublish,
    /** 발행 요청 본문에 실을 값(`checkBeforePublish` 가 읽은 이력 기준). */
    publishValue: (publishedCountAtPress: number | undefined, value: NovelPermission) =>
      novelPermissionPublishValue({ publishedCount: publishedCountAtPress, savedPermission, chosen }, value),
    /** 서버가 400 `NOVEL_PERMISSION_REQUIRED` 로 거절했다 — 고를 때까지 묻는다. */
    markRequiredByServer: () => {
      setChosen(false);
      setAlreadyAsked(true);
    },
  };
}

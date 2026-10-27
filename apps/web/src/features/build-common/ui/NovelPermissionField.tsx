import { cn } from "@ai-character-chat/ui/lib/utils";
import type { Ref } from "react";

import {
  isNovelPermission,
  NOVEL_PERMISSION_FIELD_LABEL,
  NovelPermissionPicker,
  type NovelPermission,
} from "@/entities/content";
import { RequiredText } from "@/shared/ui/RequiredText";

import type { NovelPermissionChoiceView } from "../lib/useNovelPermissionChoice";

type NovelPermissionFieldProps = {
  idPrefix: string;
  /** RHF `Controller` 의 `field` 에서 쓰는 셋. */
  value: string;
  onChange: (value: NovelPermission) => void;
  fieldRef: Ref<HTMLDivElement>;
  choice: NovelPermissionChoiceView;
  earningRate: string | null;
};

/**
 * 공개 준비 탭의 "다른 회원의 소설 만들기" 칸. 두 빌더가 같은 꼴로 쓴다.
 *
 * 첫 발행 전 아직 고르지 않았으면 세 줄을 모두 끄고 칸에 별표와 "아직 고르지 않았어요"를 단다. 그림만 비우고 폼 값은 그대로다 —
 * 자동저장이 그 칸을 바꾸지 않는다. 발행이 이 칸 때문에 막히면 아래 안내 문장이 오류 색으로 바뀐다. 발행작이면 이 칸과 아래 파생 소설
 * 스위치가 발행을 기다리지 않고 저장 즉시 적용된다는 한 줄을 먼저 둔다.
 */
export function NovelPermissionField({ idPrefix, value, onChange, fieldRef, choice, earningRate }: NovelPermissionFieldProps) {
  const labelId = `${idPrefix}-novel-permission-label`;
  const hintId = `${idPrefix}-novel-permission-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      {choice.publishedContentId !== undefined && (
        <p className="mb-1.5 text-sm break-keep text-muted-foreground">
          아래 두 칸은 발행하지 않아도 저장되는 즉시 적용돼요.
        </p>
      )}
      <span id={labelId} className="text-sm leading-none font-medium">
        {choice.isUnchosen ? <RequiredText>{NOVEL_PERMISSION_FIELD_LABEL}</RequiredText> : NOVEL_PERMISSION_FIELD_LABEL}
      </span>
      {choice.isUnchosen && <p className="text-xs text-muted-foreground">아직 고르지 않았어요</p>}
      <NovelPermissionPicker
        ref={fieldRef}
        value={choice.isUnchosen || !isNovelPermission(value) ? undefined : value}
        onValueChange={(next) => {
          onChange(next);
          choice.onChoose();
        }}
        labelledBy={labelId}
        describedBy={choice.isUnchosen ? hintId : undefined}
        invalid={choice.isBlocked}
        earningRate={earningRate}
      />
      {choice.isUnchosen && (
        <p
          id={hintId}
          className={cn("text-xs break-keep", choice.isBlocked ? "text-destructive-text" : "text-muted-foreground")}
        >
          처음 발행하기 전에 하나를 골라 주세요. 발행한 뒤에도 바꿀 수 있어요.
        </p>
      )}
    </div>
  );
}

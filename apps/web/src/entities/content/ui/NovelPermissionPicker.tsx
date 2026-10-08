import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import type { Ref } from "react";

import {
  isNovelPermission,
  NOVEL_PERMISSION_COPY,
  NOVEL_PERMISSION_VALUES,
  type NovelPermission,
} from "../model/novelPermission";

type NovelPermissionPickerProps = {
  value: NovelPermission;
  onValueChange: (value: NovelPermission) => void;
  ref?: Ref<HTMLDivElement>;
} & (
  | {
      /** 화면에 보이는 칸 라벨의 id. 그룹의 접근 이름을 그 글자에서 얻어 둘이 갈라지지 않게 한다. */
      labelledBy: string;
      label?: never;
    }
  | {
      /** 가리킬 라벨 요소가 없는 자리(모달 제목은 다이얼로그 이름이 이미 쓴다)에서 그룹 이름. */
      label: string;
      labelledBy?: never;
    }
);

const ITEM_CLASS =
  "group/novel-permission-option h-auto min-h-11 w-full justify-start px-3.5 py-2.5 whitespace-normal hover:bg-secondary";

/** 행 안 설명 글자는 행 표면이 한 칸 오르면(hover `secondary`, 선택 `primary/10` 틴트) 잉크도 `foreground` 로 올린다 —
 * 같은 모양의 대화 프로필·모델 목록과 같은 처방이다(라이트 `muted-foreground` 가 오른 표면 위에서 AA 미달). */
const DESCRIPTION_CLASS =
  "text-xs break-keep text-muted-foreground group-hover/novel-permission-option:text-foreground group-data-[state=on]/novel-permission-option:text-foreground";

/** 소설 만들기 허락 단계 세 줄. 각 줄이 문장 하나를 달고 있어 칩이 아니라 세로 목록이고, 선택은 틴트(`variant="list"`)다 —
 * 같은 화면의 `primary` 솔리드는 발행·저장 버튼 하나여야 한다. `hover:bg-secondary` 는 모달 표면(`popover`)에서
 * 프리미티브의 `hover:bg-muted` 가 표면과 같은 값이라 사라지는 것을 한 칸 올린다. 빌더(페이지 배경)와 발행 후 설정
 * 모달 두 자리가 같은 줄을 그리도록 여기 한 곳에 둔다. */
export function NovelPermissionPicker({ value, onValueChange, labelledBy, label, ref }: NovelPermissionPickerProps) {
  return (
    <ToggleGroup
      ref={ref}
      type="single"
      variant="list"
      orientation="vertical"
      value={value}
      // 고른 줄을 다시 누르면 Radix 가 "" 를 보낸다 — 선택은 언제나 하나라 무시한다.
      onValueChange={(next) => isNovelPermission(next) && onValueChange(next)}
      aria-labelledby={labelledBy}
      aria-label={label}
      className="w-full flex-col gap-1.5"
    >
      {NOVEL_PERMISSION_VALUES.map((permission) => (
        <ToggleGroupItem key={permission} value={permission} className={ITEM_CLASS}>
          <span className="flex flex-col gap-0.5 text-left">
            <span className="text-sm font-medium">{NOVEL_PERMISSION_COPY[permission].label}</span>
            <span className={DESCRIPTION_CLASS}>{NOVEL_PERMISSION_COPY[permission].description}</span>
          </span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

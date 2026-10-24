import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { useId } from "react";

import { hasChapterModelChoice, type ChapterModelOption, type NovelChapterModelId } from "../model/chapterModel";

type ChapterModelSelectProps = {
  /** 서버가 준 고를 수 있는 모델과(정해져 있으면) 그 동작의 금액. 고를 수 없는 모델은 비활성 + 이유로 보인다. */
  options: ChapterModelOption[];
  value: NovelChapterModelId;
  onValueChange: (modelId: NovelChapterModelId) => void;
};

/** 화 확인 화면의 글쓰기 모델 선택. 고를 것이 하나뿐이면(소설 상위 모델 허용이 없으면) 아무것도 그리지 않는다 — 그
 * 계정의 확인 화면은 이 선택이 생기기 전과 같다.
 *
 * 목록형 토글이 아니라 셀렉트인 이유: 이 화면의 주 결정은 따로 있고(끝낼 턴·다시 만들지) 모델은 직전 값이 골라져
 * 있는 부수 선택이다. 한 줄로 접어 두면 확인 화면의 높이와 시선이 그대로이고, 펼친 목록 행이나 솔리드 칩이 실행
 * 버튼과 같은 무게로 경쟁하지 않는다. 금액이 모델만으로 정해지는 동작(다시 만들기)은 항목에 금액을 붙여 펼친 채로
 * 비교할 수 있게 하고, 고른 값의 금액은 아래 금액 줄이 다시 말한다. 새 화 만들기는 끝 턴을 골라야 금액이 정해져
 * 항목에 금액이 없다. */
export function ChapterModelSelect({ options, value, onValueChange }: ChapterModelSelectProps) {
  const triggerId = useId();
  if (!hasChapterModelChoice(options)) return null;

  function handleValueChange(next: string) {
    const option = options.find((item) => item.id === next && item.disabledReason === undefined);
    if (option) onValueChange(option.id);
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
      <Label htmlFor={triggerId}>글쓰기 모델</Label>
      <Select value={value} onValueChange={handleValueChange}>
        <SelectTrigger id={triggerId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.id} value={option.id} {...(option.disabledReason === undefined ? {} : UNSELECTABLE_ITEM_PROPS)}>
              {toOptionLabel(option)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function preventSelect(event: { preventDefault: () => void }) {
  event.preventDefault();
}

/** 고를 수 없는 항목. `disabled` 를 쓰지 않는다 — Radix 가 그 항목을 화살표 이동·타입어헤드에서 통째로 빼, 이유(항목 글이 곧 접근
 * 이름이다)가 키보드·스크린리더에 닿지 않는다. 대신 `aria-disabled` 로 순회에 남기고, Radix 가 고르는 세 길(Enter·Space 키, 마우스
 * pointerup, 터치 click)만 `preventDefault` 로 막는다 — Radix 의 항목 처리기는 앞선 처리기가 기본 동작을 막으면 건너뛴다. 화살표 키는
 * 막지 않는다(목록의 이동 처리도 같은 검사를 거쳐, 막으면 이동이 멈춘다). 흐림은 프리미티브의 비활성 항목과 같은 값이다.
 *
 * 글자 찾기(타입어헤드)에서는 `disabled` 때처럼 빠져야 한다 — 닫힌 트리거에서 글자를 치면 Radix 가 그 글자로 시작하는 항목을 바로
 * 고르는데, 못 고르는 항목이 걸리면 고르기가 막혀 값이 그대로라 같은 글자로 뒤의 고를 수 있는 항목에 닿지 못한다. 그래서 찾기 글
 * (`textValue`)을 칠 수 없는 글자(폭 없는 공백) 하나로 둔다. 빈 글이면 Radix 가 항목 글로 채운다. 접근 이름은 찾기 글이 아니라 항목
 * 글이 정한다(`aria-labelledby`). */
const UNSELECTABLE_ITEM_PROPS = {
  "aria-disabled": true,
  textValue: "​",
  className: "aria-disabled:opacity-65",
  onKeyDown: (event: { key: string; preventDefault: () => void }) => {
    if (event.key === "Enter" || event.key === " ") event.preventDefault();
  },
  onPointerUp: preventSelect,
  onClick: preventSelect,
} as const;

/** 항목 한 줄. 고를 수 없으면 금액 대신 이유다 — 못 고르는 항목의 금액은 비교할 거리가 아니다. */
function toOptionLabel(option: ChapterModelOption): string {
  if (option.disabledReason !== undefined) return `${option.name} · ${option.disabledReason}`;
  if (option.cost === undefined) return option.name;
  return `${option.name} · 클로버 ${option.cost.toLocaleString()}개`;
}

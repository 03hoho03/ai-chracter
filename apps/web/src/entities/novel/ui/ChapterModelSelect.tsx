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
            <SelectItem key={option.id} value={option.id} disabled={option.disabledReason !== undefined}>
              {toOptionLabel(option)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** 항목 한 줄. 고를 수 없으면 금액 대신 이유다 — 못 고르는 항목의 금액은 비교할 거리가 아니다. */
function toOptionLabel(option: ChapterModelOption): string {
  if (option.disabledReason !== undefined) return `${option.name} · ${option.disabledReason}`;
  if (option.cost === undefined) return option.name;
  return `${option.name} · 클로버 ${option.cost.toLocaleString()}개`;
}

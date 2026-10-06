import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { useId } from "react";

import { chapterModelCost, hasChapterModelChoice, type NovelChapterModel, type NovelChapterModelId } from "../model/chapterModel";

type ChapterModelSelectProps = {
  models: NovelChapterModel[];
  value: NovelChapterModelId;
  onValueChange: (modelId: NovelChapterModelId) => void;
  /** 어느 가격을 보일지 — 장 만들기와 다시 만들기는 가격 칸이 따로다. */
  kind: "generate" | "regenerate";
};

/** 장 확인 화면의 글쓰기 모델 선택. 고를 것이 하나뿐이면(소설 상위 모델 허용이 없으면) 아무것도 그리지 않는다 — 그
 * 계정의 확인 화면은 이 선택이 생기기 전과 같다.
 *
 * 목록형 토글이 아니라 셀렉트인 이유: 이 화면의 주 결정은 따로 있고(끝낼 턴·다시 만들지) 모델은 직전 값이 골라져
 * 있는 부수 선택이다. 한 줄로 접어 두면 확인 화면의 높이와 시선이 그대로이고, 펼친 목록 행이나 솔리드 칩이 실행
 * 버튼과 같은 무게로 경쟁하지 않는다. 각 항목에 가격을 붙여 펼친 채로 비교할 수 있게 하고, 고른 값의 금액은 아래
 * 금액 줄이 다시 말한다. */
export function ChapterModelSelect({ models, value, onValueChange, kind }: ChapterModelSelectProps) {
  const triggerId = useId();
  if (!hasChapterModelChoice(models)) return null;

  function handleValueChange(next: string) {
    const model = models.find((item) => item.id === next);
    if (model) onValueChange(model.id);
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
      <Label htmlFor={triggerId}>글쓰기 모델</Label>
      <Select value={value} onValueChange={handleValueChange}>
        <SelectTrigger id={triggerId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {models.map((model) => (
            <SelectItem key={model.id} value={model.id}>
              {model.name} · 클로버 {chapterModelCost(models, model.id, kind, 0).toLocaleString()}개
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

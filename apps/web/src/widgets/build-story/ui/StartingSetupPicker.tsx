import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useId } from "react";

type StartingSetupPickerProps = {
  startingSetups: readonly { id: string; name: string }[];
  selectedIndex: number;
  onSelect: (startingSetupId: string) => void;
  /** 이 탭이 시작설정마다 따로 정하는 것("스탯"·"상황 노트"·"엔딩"). 뒤 조사는 끝 글자의 받침으로 고른다. */
  itemNoun: string;
  /** 뒤에 붙는 한 문장(예: 0개여도 발행할 수 있다는 안내). */
  note: string;
};

/**
 * 스탯·상황 노트·엔딩 탭 머리의 시작설정 고르기. 세 탭은 시작설정마다 독립 목록이라 먼저 시작설정을 고른다.
 *
 * 시작설정이 하나면 고를 것이 없으니 칩을 그리지 않고 지금 어느 시작설정의 목록인지 문장으로만 알린다 — 선택된 칩 하나는
 * 핑크 솔리드 채움이라, 고를 수도 없는 것이 화면에서 발행 버튼과 함께 가장 밝은 물체가 됐다(화면당 `primary` 솔리드는
 * 하나). 둘 이상이면 칩으로 고른다.
 */
export function StartingSetupPicker({ startingSetups, selectedIndex, onSelect, itemNoun, note }: StartingSetupPickerProps) {
  const labelId = useId();
  const explanation = `${itemNoun}${topicParticle(itemNoun)} 시작설정마다 따로 정해요. ${note}`;

  if (startingSetups.length === 1) {
    return (
      <div className="flex flex-col gap-1.5">
        {/* 라벨(`leading-none`)과 달리 시작설정 이름이 길면 두 줄로 접히는 문장이라 줄 간격을 둔다 — 줄 높이 1이면 두 줄이
            맞붙는다. 띄어쓰기 없는 긴 이름도 화면 밖으로 넘치지 않게 마지막 수단으로 어디서든 끊는다. */}
        <p className="text-sm leading-snug font-medium break-keep wrap-anywhere">
          ‘{setupName(startingSetups[0]?.name, 0)}’의 {itemNoun}
        </p>
        <p className="text-sm break-keep text-muted-foreground">{explanation}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span id={labelId} className="text-sm leading-none font-medium">
        시작설정
      </span>
      <p className="text-sm break-keep text-muted-foreground">{explanation}</p>
      <ToggleGroup
        type="single"
        variant="outline"
        className="flex-wrap"
        value={startingSetups[selectedIndex]?.id ?? ""}
        onValueChange={(value) => value && onSelect(value)}
        aria-labelledby={labelId}
      >
        {startingSetups.map((setup, index) => (
          <ToggleGroupItem key={setup.id} value={setup.id} aria-label={setupName(setup.name, index)}>
            {setupName(setup.name, index)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

/** 보조사 — 끝 글자에 받침이 있으면 "은", 없으면 "는"(`상황 노트는`). 한글이 아닌 글자로 끝나면 둘 다 적는다. */
function topicParticle(word: string): string {
  const last = word.codePointAt(word.length - 1);
  const isHangulSyllable = last !== undefined && last >= 0xac00 && last <= 0xd7a3;
  if (!isHangulSyllable) return "은(는)";
  return (last - 0xac00) % 28 === 0 ? "는" : "은";
}

function setupName(name: string | undefined, index: number): string {
  return name || `시작설정 ${index + 1}`;
}

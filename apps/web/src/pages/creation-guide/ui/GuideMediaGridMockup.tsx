import { cn } from "@ai-character-chat/ui/lib/utils";
import { EyeOff, ImageIcon, Plus } from "lucide-react";

import type { MediaGridMockupValue } from "../model/mediaGridDescription";

type GuideMediaGridMockupProps = MediaGridMockupValue;

/**
 * 미디어 북 배치표 그림(인물 열 × 장면 줄). 예시 작품의 칸 그림은 비로그인으로 가져올 수 없어 그림이 있는 칸은 자리표시
 * 아이콘으로만 그린다. 칸 크기·모양은 빌더 배치표와 같고, 고른 칸은 빌더의 강조 테두리 대신 무채 테두리다(그림은 누를 수
 * 없어 강조색을 받지 않는다).
 *
 * 표 전체가 그림이라 칸마다 낭독시키지 않는다(`role="presentation"`). 대신 액자 캡션에 붙는 설명 문장
 * (`model/mediaGridDescription.ts`)이 칸 수·숨긴 칸·고른 칸을 말한다.
 */
export function GuideMediaGridMockup({ people, scenes, cells, selected }: GuideMediaGridMockupProps) {
  const cellAt = (person: number, scene: number) =>
    cells.find((cell) => cell.person === person && cell.scene === scene);

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-xs text-muted-foreground">
        인물 {people.length} · 장면 {scenes.length}만 골라 보여 줘요
      </p>
      <div
        role="presentation"
        className="grid w-fit gap-1.5"
        // 열 수가 원고 값(인물 수)에서 정해져 정적 클래스로 쓸 수 없다. 이름 열 64px + 칸 80px 은 빌더 배치표와 같은 칸 크기다.
        style={{ gridTemplateColumns: `4rem repeat(${people.length}, 5rem)` }}
      >
        <span />
        {people.map((person) => (
          <span key={person} className="truncate text-center text-xs font-medium text-foreground">
            {person}
          </span>
        ))}
        {scenes.map((scene, sceneIndex) => (
          <div key={scene} className="contents">
            <span className="self-center truncate text-xs font-medium text-foreground">{scene}</span>
            {people.map((person, personIndex) => {
              const cell = cellAt(personIndex, sceneIndex);
              const isSelected = selected.person === personIndex && selected.scene === sceneIndex;
              return (
                <span
                  key={person}
                  className={cn(
                    "relative flex size-20 items-center justify-center rounded-md text-muted-foreground",
                    cell ? "border border-foreground/10 bg-muted" : "border border-dashed border-input",
                    isSelected && "border-2 border-foreground",
                  )}
                >
                  {cell ? <ImageIcon aria-hidden className="size-5" /> : <Plus aria-hidden className="size-5" />}
                  {cell?.isHiddenInChat && (
                    <span className="absolute top-1 left-1 inline-flex size-5 items-center justify-center rounded-md bg-scrim/70 text-scrim-foreground">
                      <EyeOff aria-hidden className="size-3" />
                    </span>
                  )}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

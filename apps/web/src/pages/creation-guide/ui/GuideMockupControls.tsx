import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check, ChevronDown } from "lucide-react";

import {
  FieldLabelText,
  STORY_FIELD_LABELS,
  type ConditionalStoryFieldKey,
  type StoryFieldKey,
} from "@/features/build-story";

import { GUIDE_SUMMARY_CLASS } from "../config/guideStyles";
import { exceedsClampLines } from "../model/clampedText";
import type { MockupChoice } from "../model/mockupChoices";

// 빌더 칸의 "그림". 진짜 입력 요소(`Input`·`Switch` 등)를 쓰지 않는다 — 읽기 전용 입력칸도 Tab 이 멈추고 스크린리더가
// "편집할 수 없는 입력칸"으로 읽어, 눌러 보면 될 것 같은 오해를 그대로 만든다. 그래서 동작 없는 `div`·`span` 에 프리미티브와
// 같은 모양 값만 적는다. `packages/ui` 의 Input·Textarea·Select·Toggle·Switch 모양 값이 바뀌면 여기도 함께 고친다.
//
// 선택된 칩·켜진 스위치는 빌더와 달리 솔리드 `primary` 로 칠하지 않는다. 그림은 누를 수 없는데, 한 화면에 누를 수 없는
// 핑크 채움이 여럿 서면 "지금 눌러야 할 단 하나"에만 밝은 채움을 쓰는 규칙이 무너진다. 무채 윤곽과 체크 글리프로 고른
// 것을 알린다. 목업 어디에도 hover 반응·포인터 커서가 없고, 값 글자는 복사할 수 있게 둔다.

/** 한 줄 입력칸 모양 — `Input` 과 같은 높이·반경·컨트롤 보더. */
const INPUT_CLASS = "flex h-9 min-w-0 items-center rounded-lg border border-input px-3 text-sm text-foreground";

type MockupLabelProps = {
  fieldKey: StoryFieldKey;
};

/** 칸 라벨 글자. 빌더와 같은 라벨 상수·같은 빨간 필수 별표를 그린다(그림이 아니라 글자라 공용 컴포넌트를 쓴다). */
export function MockupLabel({ fieldKey }: MockupLabelProps) {
  return (
    <span className="text-sm leading-none font-medium text-foreground">
      {isConditionalKey(fieldKey) ? (
        // 원고 검사가 조건부 필수 칸의 예시를 필수가 되는 쪽(상시 적용이 꺼진 노트)으로만 허락한다.
        <FieldLabelText field={fieldKey} isRequired />
      ) : (
        <FieldLabelText field={fieldKey} />
      )}
    </span>
  );
}

function isConditionalKey(key: StoryFieldKey): key is ConditionalStoryFieldKey {
  const { required }: { required: boolean | "conditional" } = STORY_FIELD_LABELS[key];
  return required === "conditional";
}

type MockupInputProps = {
  value: string;
  /** 값이 비었을 때 빌더처럼 흐리게 보이는 자리표시. */
  placeholder?: string;
  className?: string;
};

export function MockupInput({ value, placeholder, className }: MockupInputProps) {
  return (
    <div className={cn(INPUT_CLASS, className)}>
      {value ? (
        <span className="truncate">{value}</span>
      ) : (
        <span className="truncate text-muted-foreground">{placeholder}</span>
      )}
    </div>
  );
}

export function MockupSelect({ value, className }: { value: string; className?: string }) {
  return (
    <div className={cn(INPUT_CLASS, "justify-between gap-2", className)}>
      <span className="truncate">{value}</span>
      <ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </div>
  );
}

type MockupTextareaProps = {
  text: string;
  /** false 면 길어도 자르지 않는다 — 좋은 예/나쁜 예 대비처럼 이미 짧게 고른 발췌는 다 보여야 비교가 된다. */
  clampsLongText?: boolean;
};

/**
 * 여러 줄 칸 모양. 빌더 칸은 글만큼 자라지만 그림은 몇 줄에서 잘라 페이지 길이를 지킨다. 넘칠 때만 "전체 보기"를 둔다 —
 * 잘림은 화면에서만이라 스크린리더는 접힌 상태에서도 글 전체를 읽는다.
 *
 * 줄높이는 빌더 칸과 같은 24px 이다(빌더 칸은 `text-base` 의 기본 줄높이). 최소 높이도 빌더 칸과 같아 한 줄짜리 값도
 * 한 줄 입력칸으로 보이지 않는다.
 */
export function MockupTextarea({ text, clampsLongText = true }: MockupTextareaProps) {
  const canClamp = clampsLongText && exceedsClampLines(text);
  return (
    <div className="group/clip flex flex-col gap-2">
      {/* 잘림은 안쪽 글 상자에 건다 — 테두리 상자에 걸면 잘린 다음 줄이 아래 패딩 자리에 비쳐 보인다. */}
      <div className="min-h-16 rounded-lg border border-input px-3 py-2 text-sm leading-6 whitespace-pre-wrap break-keep wrap-break-word text-foreground">
        <div className={cn(canClamp && "line-clamp-4 group-has-[details[open]]/clip:line-clamp-none")}>{text}</div>
      </div>
      {canClamp && (
        <details className="group">
          <summary className={cn(GUIDE_SUMMARY_CLASS, "w-fit")}>
            <ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground group-open:rotate-180" />
            <span className="group-open:hidden">전체 보기</span>
            <span className="hidden group-open:inline">접기</span>
          </summary>
        </details>
      )}
    </div>
  );
}

type MockupChoiceChipsProps = {
  choices: readonly MockupChoice[];
};

/**
 * 하나를 고르는 칩 묶음(템플릿·타겟·공개범위·적용 대상). 빌더 묶음은 줄을 바꾸지 않지만 그림은 바꾼다 — 넘치는 칩이
 * 페이지를 가로로 밀거나, 그림 속에 가로 스크롤이 생겨 만져 볼 것처럼 보이지 않게.
 */
export function MockupChoiceChips({ choices }: MockupChoiceChipsProps) {
  return (
    <ul className="flex flex-wrap gap-2">
      {choices.map((choice) => (
        <li
          key={choice.label}
          className={cn(
            "inline-flex h-9 items-center gap-1 rounded-full border px-4 text-sm font-medium whitespace-nowrap",
            choice.isSelected ? "border-foreground text-foreground" : "border-input text-muted-foreground",
          )}
        >
          {choice.isSelected && <Check aria-hidden className="size-4 shrink-0" />}
          {choice.label}
          {choice.isSelected && <span className="sr-only"> (선택됨)</span>}
        </li>
      ))}
    </ul>
  );
}

/** 입력한 값이 칩으로 쌓이는 칸(키워드·해시태그·추천 답변). 지우기 버튼은 그리지 않는다. */
export function MockupValueChips({ items }: { items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-2">
      {items.map((item) => (
        <li
          key={item}
          className="inline-flex items-center rounded-full border border-border px-3 py-1 text-xs text-foreground"
        >
          {item}
        </li>
      ))}
    </ul>
  );
}

/**
 * 스위치 모양 — 빌더 `Switch` 와 같은 크기·투명 보더·꺼짐 색이고, 켜짐 트랙만 `primary` 대신 `foreground` 다. 상태는
 * 옆 글자("켜짐"/"꺼짐")가 말해 색을 구별하지 못해도 읽힌다. 높이 18.4px 은 그 프리미티브의 값을 그대로 옮긴 것이다.
 */
export function MockupSwitch({ isOn }: { isOn: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden
        className={cn(
          "inline-flex h-[18.4px] w-8 shrink-0 items-center rounded-full border border-transparent",
          isOn ? "justify-end bg-foreground" : "bg-input",
        )}
      >
        <span className="size-4 rounded-full bg-background" />
      </span>
      <span className="text-xs text-muted-foreground">{isOn ? "켜짐" : "꺼짐"}</span>
    </span>
  );
}

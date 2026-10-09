import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check, ChevronDown } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";

import {
  FieldLabelText,
  STORY_FIELD_LABELS,
  type ConditionalStoryFieldKey,
  type StoryFieldKey,
} from "@/features/build-story";

import { GUIDE_SUMMARY_CLASS } from "../config/guideStyles";
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

type MockupCharacterCountProps = {
  count: number;
  max: number;
};

/** 빌더 칸 아래 줄의 `n/최대` 카운터 모양. 상한에 닿을 때의 모양은 `DESIGN.md` Inputs / Fields 절의 Character count 를 따른다. */
export function MockupCharacterCount({ count, max }: MockupCharacterCountProps) {
  return (
    <span
      className={cn("self-end text-xs text-muted-foreground tabular-nums", count >= max && "font-medium text-foreground")}
    >
      {`${count}/${max}`}
    </span>
  );
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
 * 여러 줄 칸 모양. 빌더 칸은 글만큼 자라지만 그림은 네 줄에서 잘라 페이지 길이를 지킨다. 실제로 잘린 칸에만 "전체 보기"를
 * 둔다 — 글자 수로 미리 짐작하면 넓은 화면에서 네 줄 안에 다 보이는 값에도 눌러도 바뀌지 않는 줄이 남는다. 잘렸는지는
 * 그린 뒤 높이로 재되 화면에 칠하기 전(레이아웃 효과)에 정해, 줄이 나타났다 사라지는 깜빡임이 없다. 잘림은 화면에서만이라
 * 스크린리더는 접힌 상태에서도 글 전체를 읽는다.
 *
 * "전체 보기"는 칸 블록의 "자세히"·"나쁜 예"보다 한 단계 작고 흐리게 둔다 — 그 둘은 칸 블록의 접기고, 이것은 그림 속
 * 칸 하나를 늘리는 것이라 같은 무게면 세 줄이 한 종류로 읽힌다.
 *
 * 줄높이는 빌더 칸과 같은 24px 이다(빌더 칸은 `text-base` 의 기본 줄높이). 최소 높이도 빌더 칸과 같아 한 줄짜리 값도
 * 한 줄 입력칸으로 보이지 않는다.
 */
export function MockupTextarea({ text, clampsLongText = true }: MockupTextareaProps) {
  const textRef = useRef<HTMLDivElement>(null);
  const rowRef = useRef<HTMLDetailsElement>(null);
  const [hasRow, setHasRow] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  // 펼친 동안은 재지 않는다 — 잘림이 풀려 "안 잘림"으로 읽히면 "접기" 줄이 사라진다. 크기가 바뀌면(창 크기·두 열 전환,
  // 아직 안 잘린 짧은 값이 글자 간격 덮어쓰기 등으로 줄이 늘어 높이가 자라는 경우) 다시 재고, 글꼴이 늦게 들어와 줄바꿈이 달라지는 경우도 잡는다(잘린 상자는 높이가 그대로라 크기 감시로는 모른다).
  useLayoutEffect(() => {
    const element = textRef.current;
    if (!clampsLongText || isExpanded || !element) return;
    // 포커스를 가진 줄은 안 잘리게 됐어도 남긴다. 펼친 채 화면을 돌려(좁은→넓은 폭) 접으면 그 자리에서 잘림이 없어지는데,
    // 그때 줄을 내리면 키보드·스크린리더 포커스가 문서 맨 앞(body)으로 튕긴다. 남은 줄은 포커스가 떠난 뒤 다음 재기(폭
    // 변화 등)에서 내린다 — 포커스가 떠나는 순간 내리면 그 아래 내용이 클릭 도중에 밀려 올라온다.
    const measure = () => {
      const isClamped = element.scrollHeight > element.clientHeight;
      const isRowFocused = rowRef.current?.contains(document.activeElement) ?? false;
      setHasRow(isClamped || isRowFocused);
    };
    measure();
    // 폭·높이가 둘 다 그대로인 알림은 건너뛴다 — 감시를 걸면 바로 한 번 오는 첫 알림이 그렇다. 그 알림이 늦게 오면 이미
    // 줄을 떠난 포커스를 보고 줄을 내려, 크기가 바뀌지 않았는데도 아래 내용이 밀려 올라온다. 폭만 보면 안 된다: 안 잘린
    // 짧은 값은 폭이 그대로여도 줄이 늘면 높이가 자라며 잘리기 시작한다.
    let measuredWidth = element.clientWidth;
    let measuredHeight = element.clientHeight;
    const observer = new ResizeObserver(() => {
      if (element.clientWidth === measuredWidth && element.clientHeight === measuredHeight) return;
      measuredWidth = element.clientWidth;
      measuredHeight = element.clientHeight;
      measure();
    });
    observer.observe(element);
    let isActive = true;
    void document.fonts.ready.then(() => {
      if (isActive) measure();
    });
    return () => {
      isActive = false;
      observer.disconnect();
    };
  }, [clampsLongText, isExpanded, text]);

  return (
    <div className="flex flex-col gap-2">
      {/* 잘림은 안쪽 글 상자에 건다 — 테두리 상자에 걸면 잘린 다음 줄이 아래 패딩 자리에 비쳐 보인다. */}
      <div className="min-h-16 rounded-lg border border-input px-3 py-2 text-sm leading-6 whitespace-pre-wrap break-keep wrap-break-word text-foreground">
        <div ref={textRef} className={cn(clampsLongText && !isExpanded && "line-clamp-4")}>
          {text}
        </div>
      </div>
      {(hasRow || isExpanded) && (
        <details ref={rowRef} className="group" onToggle={(event) => setIsExpanded(event.currentTarget.open)}>
          <summary className={cn(GUIDE_SUMMARY_CLASS, "w-fit gap-1.5 text-xs text-muted-foreground hover:text-foreground")}>
            <ChevronDown aria-hidden className="size-3.5 shrink-0 group-open:rotate-180" />
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
  /** 빌더 토글의 크기. `sm` 은 규칙 사이 관계 토글처럼 작은 묶음이다. */
  size?: "default" | "sm";
  className?: string;
};

/**
 * 하나를 고르는 칩 묶음(템플릿·타겟·공개범위·적용 대상·규칙 사이 관계). 빌더 묶음은 줄을 바꾸지 않지만 그림은 바꾼다 —
 * 넘치는 칩이 페이지를 가로로 밀거나, 그림 속에 가로 스크롤이 생겨 만져 볼 것처럼 보이지 않게.
 */
export function MockupChoiceChips({ choices, size = "default", className }: MockupChoiceChipsProps) {
  return (
    <ul className={cn("flex flex-wrap gap-2", className)}>
      {choices.map((choice) => (
        <li
          key={choice.label}
          className={cn(
            "inline-flex items-center gap-1 rounded-full border font-medium whitespace-nowrap",
            size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm",
            choice.isSelected ? "border-foreground text-foreground" : "border-input text-muted-foreground",
          )}
        >
          {choice.isSelected && <Check aria-hidden className={cn("shrink-0", size === "sm" ? "size-3.5" : "size-4")} />}
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

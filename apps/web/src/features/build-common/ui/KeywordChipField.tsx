import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { countCharacters } from "@/shared/lib/text/characterCount";
import { CharacterCount } from "@/shared/ui/CharacterCount";

type ChipStyle = "filled" | "outlined";

type KeywordChipFieldProps = {
  /** 입력칸·안내 문장의 id 접두. 노트마다 달라야 한다. */
  idPrefix: string;
  /** 개수·목록의 접근 이름에 쓰는 칸 이름. 별표를 넣지 않는다. */
  label: string;
  /** 화면 라벨. 필수 별표는 여기에만 붙인다. */
  labelContent: ReactNode;
  /** 칩 이름을 읽어 주는 접미 — "`은빛열쇠` 트리거 키워드 삭제"처럼 삭제 버튼 이름에 붙는다. */
  chipNoun: string;
  placeholder: string;
  keywords: readonly string[];
  limit: number;
  limitReason: string;
  /** 항목 하나의 글자 수 상한. 입력칸 아래 카운터에 쓴다 — 넘는 글은 넣을 때 `validate` 가 거절한다. */
  itemMaxLength: number;
  /** 입력칸 글을 넣을 값으로 편다. 기본은 앞뒤 공백 제거이고, 카운터도 편 값을 센다. */
  normalize?: (input: string) => string;
  /** 넣어도 되면 undefined, 아니면 거절 이유(길이·빈 값·정규화 중복). 받는 값은 `normalize` 를 거친 값이다. 개수
   * 상한은 이 컴포넌트가 먼저 막는다. */
  validate: (keyword: string) => string | undefined;
  onAdd: (keyword: string) => void;
  onRemove: (keyword: string) => void;
  /** 칩 모양 — 트리거는 채움, 금지는 윤곽으로 갈라 두 목록이 훑을 때 섞이지 않게 한다. */
  chipStyle: ChipStyle;
  /** 칩 글자 앞에 그리는 표지(해시태그의 `#`). 값에는 넣지 않는다. */
  chipPrefix?: string;
  /** 칸 전체를 잠근다(상시 노트의 트리거 키워드). 사유 문장은 호출부가 `disabledReasonId` 로 가리킨다. */
  disabled?: boolean;
  disabledReasonId?: string;
  /** 발행 검사의 오류(목록 자리). */
  error?: string;
  fieldPath: string;
};

const CHIP_STYLE_CLASS: Record<ChipStyle, string> = {
  filled: "bg-secondary text-secondary-foreground",
  outlined: "border border-border text-foreground",
};

/**
 * 칩 입력 — 입력칸 + 추가 + 칩 목록 + 개수. 키워드 노트의 트리거·금지 키워드와 두 빌더의 해시태그가 같은 규칙(개수
 * 상한, 항목 글자 수 상한, 대소문자만 다른 중복 거절)이라 함께 쓴다. 넣을 때 검사하는 칸이다(카운터 규칙은 `DESIGN.md`
 * Inputs / Fields 절의 Character count).
 */
export function KeywordChipField({
  idPrefix,
  label,
  labelContent,
  chipNoun,
  placeholder,
  keywords,
  limit,
  limitReason,
  itemMaxLength,
  normalize = (input) => input.trim(),
  validate,
  onAdd,
  onRemove,
  chipStyle,
  chipPrefix = "",
  disabled = false,
  disabledReasonId,
  error,
  fieldPath,
}: KeywordChipFieldProps) {
  const [input, setInput] = useState("");
  const [refusal, setRefusal] = useState<string>();
  const isFull = keywords.length >= limit;
  const inputId = `${idPrefix}-input`;
  const countId = `${idPrefix}-count`;
  const lengthId = `${idPrefix}-length`;
  const limitId = `${idPrefix}-limit`;
  const refusalId = `${idPrefix}-refusal`;
  const errorId = `${idPrefix}-error`;
  const removeButtonId = (index: number) => `${idPrefix}-remove-${index}`;
  // 칩을 지운 뒤 포커스를 둘 요소. 렌더가 끝나 칩 목록이 줄어든 뒤에야 그 자리에 맞는 버튼이 있으므로 effect 에서 옮긴다.
  const pendingFocusIdRef = useRef<string | undefined>(undefined);
  const describedBy =
    [
      countId,
      lengthId,
      disabled ? disabledReasonId : undefined,
      !disabled && isFull ? limitId : undefined,
      refusal ? refusalId : undefined,
      error ? errorId : undefined,
    ]
      .filter(Boolean)
      .join(" ") || undefined;

  useEffect(() => {
    const targetId = pendingFocusIdRef.current;
    if (!targetId) return;
    pendingFocusIdRef.current = undefined;
    document.getElementById(targetId)?.focus();
  }, [keywords]);

  function handleRemove(keyword: string, index: number) {
    setRefusal(undefined);
    onRemove(keyword);
    // 다음 칩(지운 뒤엔 같은 순번으로 당겨진다) → 없으면 앞 칩 → 없으면 입력칸으로 포커스를 옮긴다. 삭제 버튼이
    // 사라지며 포커스가 body 로 떨어지면 키보드로 칩을 여럿 지울 때마다 처음부터 다시 Tab 해야 한다.
    if (index + 1 < keywords.length) pendingFocusIdRef.current = removeButtonId(index);
    else if (index > 0) pendingFocusIdRef.current = removeButtonId(index - 1);
    else pendingFocusIdRef.current = inputId;
  }

  function handleAdd() {
    // 꽉 찬 상태의 이유는 이미 입력칸 아래 문장이 늘 보여 주므로 같은 말을 오류로 한 번 더 띄우지 않는다.
    if (disabled || isFull) return;
    const value = normalize(input);
    if (!value) {
      setInput("");
      return;
    }
    // 서버가 거절할 키워드(길이·개수·대소문자만 다른 중복)는 폼에 넣지 않는다 — 자동저장은 발행 검사를 거치지 않아
    // 한 번 들어가면 그 초안 저장 전체가 멈춘다. 거절할 때는 쓴 글을 지우지 않고 이유를 보여 준다.
    const reason = validate(value);
    if (reason) {
      setRefusal(reason);
      return;
    }
    setInput("");
    onAdd(value);
  }

  return (
    <div className="flex flex-col gap-1.5" data-field-path={fieldPath}>
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={inputId}>{labelContent}</Label>
        <span id={countId} className="text-xs tabular-nums text-muted-foreground">
          <span className="sr-only">{label} </span>
          {keywords.length}/{limit}
        </span>
      </div>
      <div className="flex gap-2">
        <Input
          id={inputId}
          placeholder={placeholder}
          value={input}
          disabled={disabled}
          aria-invalid={!!refusal || !!error}
          aria-describedby={describedBy}
          onChange={(event) => {
            setInput(event.target.value);
            setRefusal(undefined);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
            event.preventDefault();
            handleAdd();
          }}
        />
        {/* 상한에서도 버튼을 트리에 남기고 `aria-disabled` 로만 잠근다 — `disabled` 는 누르는 순간 포커스를
            body 로 떨어뜨리고, 지우면 왜 못 넣는지가 사라진다. 실제 차단은 handleAdd 첫 줄의 꽉 참 검사다
            (Enter 는 버튼 잠금을 지나 handleAdd 로 바로 온다). */}
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          aria-disabled={!disabled && isFull}
          aria-describedby={!disabled && isFull ? limitId : undefined}
          className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
          onClick={handleAdd}
        >
          추가
        </Button>
      </div>
      <CharacterCount id={lengthId} count={countCharacters(normalize(input))} max={itemMaxLength} />
      {!disabled && isFull && (
        <p id={limitId} className="text-xs text-muted-foreground">
          {limitReason}
        </p>
      )}
      {!!refusal && (
        <p id={refusalId} role="alert" className="text-xs text-destructive-text">
          {refusal}
        </p>
      )}
      {keywords.length > 0 && (
        // 터치 화면에서는 × 의 누르는 영역이 40px 로 커져 칩 위아래로 8px 씩 나간다. 줄 간격을 16px 로 벌려 윗줄 칩은
        // 물론 윗줄 × 의 영역과도 겹치지 않게 한다.
        <ul
          className={cn("flex flex-wrap gap-2 pointer-coarse:gap-y-4", disabled && "opacity-65")}
          aria-label={`${label} 목록`}
        >
          {keywords.map((keyword, index) => (
            <li
              key={keyword}
              // 긴 칩은 줄 폭에서 글자만 말줄임으로 잘리고 × 는 늘 칩 안에 남는다. 잘린 이름 전체는 × 의 접근 이름에 있다.
              className={cn(
                "inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs",
                CHIP_STYLE_CLASS[chipStyle],
              )}
            >
              <span className="min-w-0 truncate">
                {chipPrefix}
                {keyword}
              </span>
              {/* 보이는 크기는 칩 안의 16px 그대로 두고 `after` 로 누르는 영역만 넓힌다(공용 체크박스·스위치와 같은 방식).
                  `after` 는 버튼의 투명 보더 1px 안쪽에서 나가므로 8px 씩이면 30×30, 터치 화면의 13px 씩이면 40×40 이다.
                  오른쪽은 칩 패딩(12px) 안팎에 머물러 옆 칩(8px 떨어짐)에 닿지 않고, 위아래는 줄 간격 안에 머문다. */}
              <Button
                id={removeButtonId(index)}
                type="button"
                variant="ghost"
                size="icon"
                className="relative size-4 shrink-0 after:absolute after:-inset-2 pointer-coarse:after:-inset-[13px]"
                disabled={disabled}
                aria-label={`${chipPrefix}${keyword} ${chipNoun} 삭제`}
                onClick={() => handleRemove(keyword, index)}
              >
                <X aria-hidden className="size-3" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {!!error && (
        <p id={errorId} role="alert" className="text-xs text-destructive-text">
          {error}
        </p>
      )}
    </div>
  );
}

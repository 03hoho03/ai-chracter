import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@ai-character-chat/ui/components/sheet";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";

type FilterOption<V extends string> = { value: V; label: string };

type SelectFilterDef<V extends string> = {
  /** DOM id·칩 키. */
  id: string;
  /** 보이는 접두 라벨("종류"). */
  label: string;
  options: readonly FilterOption<V>[];
  /** `undefined` = 기본값(거르지 않음). */
  value: V | undefined;
  /** 있으면 맨 앞에 "아무것도 거르지 않음" 항목을 이 이름으로 둔다(보통 "전체"). 고르면 `undefined` 로 바뀐다. */
  defaultLabel?: string;
  /** `sort` 는 목록을 줄이지 않고 순서만 바꿔 "필터 (n)" 수와 해제 칩에서 빠진다. */
  role?: "filter" | "sort";
  onChange: (value: V | undefined) => void;
};

/** 옵션 타입을 지워 한 배열에 담은 필터 하나. `selectFilter` 로만 만든다. */
export type FilterField = {
  id: string;
  label: string;
  options: readonly FilterOption<string>[];
  value: string | undefined;
  defaultLabel?: string;
  role: "filter" | "sort";
  /** 고른 문자열을 옵션에서 다시 찾아 좁힌 뒤 넘긴다 — 못 찾으면(기본값 항목) `undefined`. */
  select: (raw: string) => void;
};

export function selectFilter<V extends string>({ onChange, options, role = "filter", ...rest }: SelectFilterDef<V>): FilterField {
  return {
    ...rest,
    options,
    role,
    select: (raw) => onChange(options.find((option) => option.value === raw)?.value),
  };
}

type FilterBarProps = {
  /** 제출 기반 검색칸. 타이핑마다 요청하지 않는다. */
  search?: { label: string; placeholder: string; value?: string; onSubmit: (query: string | undefined) => void };
  fields: readonly FilterField[];
  /** 적용 중인 필터를 모두 푼다(필터 시트의 "필터 초기화"). */
  onReset: () => void;
};

/** Radix Select 항목은 빈 문자열 값을 받지 않아, 기본값 항목은 옵션과 겹치지 않는 표식 값으로 둔다. */
const DEFAULT_VALUE = "__default__";

/**
 * 목록 화면의 검색·필터 줄. 상태는 늘 라우트 URL search 에 있고 이 컴포넌트는 값을 받아 콜백만 부른다.
 *
 * 자기 폭(컨테이너 쿼리 `@2xl`, 672px)으로 두 모양을 가른다 — 사이드바가 접히고 펴지면 같은 뷰포트에서도 본문 폭이
 * 바뀌어서다.
 * - 넓을 때: 검색 + 셀렉트들이 한 줄에서 줄바꿈된다. 트리거마다 "종류: 전체"처럼 보이는 접두 라벨이 있고 그 라벨이
 *   접근 이름이다. 값이 기본값이면 흐린 글자, 걸렸으면 진한 글자다(색이 아니라 명도로 가른다).
 * - 좁을 때: 검색 + "필터 (n)" 버튼 → 바텀시트에 라벨 + 전폭 셀렉트를 세로로 쌓고, 걸린 필터는 아래에 해제 칩으로 남는다.
 *   시트 안 변경도 즉시 적용된다(넓을 때와 같은 동작).
 */
export function FilterBar({ search, fields, onReset }: FilterBarProps) {
  const id = useId();
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const appliedFields = fields.filter((field) => field.role === "filter" && field.value !== undefined);

  return (
    <div className="@container">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* 뒤로가기 등으로 search 의 검색어가 바뀌면 폼째 리마운트해 입력칸을 맞춘다. */}
          {!!search && <FilterSearchForm key={search.value ?? ""} {...search} />}

          {fields.map((field) => (
            <Select key={field.id} value={field.value ?? DEFAULT_VALUE} onValueChange={field.select}>
              {/* 콤보박스는 내용에서 이름을 얻지 않아 보이는 접두 라벨을 `aria-labelledby` 로 이름 삼는다(값은 콤보박스
                  값으로 따로 읽힌다). Radix 의 값 요소는 className 을 버려서 값 글자 명도는 트리거에서 자식 선택자로 건다. */}
              <SelectTrigger
                size="sm"
                aria-labelledby={`${id}-${field.id}-inline-label`}
                className={cn(
                  "hidden w-auto @2xl:flex",
                  field.value === undefined
                    ? "*:data-[slot=select-value]:text-muted-foreground"
                    : "*:data-[slot=select-value]:font-medium",
                )}
              >
                <span id={`${id}-${field.id}-inline-label`} className="text-muted-foreground">
                  {field.label}:
                </span>
                <SelectValue />
              </SelectTrigger>
              <FilterOptions field={field} />
            </Select>
          ))}

          <Sheet open={isSheetOpen} onOpenChange={setIsSheetOpen}>
            <SheetTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="@2xl:hidden"
                aria-label={appliedFields.length > 0 ? `필터, ${appliedFields.length}개 적용됨` : "필터"}
              >
                <SlidersHorizontal aria-hidden />
                필터{appliedFields.length > 0 && <span className="tabular-nums">{appliedFields.length}</span>}
              </Button>
            </SheetTrigger>
            <SheetContent side="bottom" aria-describedby={undefined} className="max-h-below-header gap-0 rounded-t-xl">
              <SheetHeader className="shrink-0 pr-14">
                <SheetTitle className="font-semibold">필터</SheetTitle>
              </SheetHeader>
              <div className="flex min-h-0 flex-col gap-4 overflow-y-auto px-4">
                {fields.map((field) => (
                  <div key={field.id} className="flex flex-col gap-1.5">
                    <Label htmlFor={`${id}-${field.id}`}>{field.label}</Label>
                    <Select value={field.value ?? DEFAULT_VALUE} onValueChange={field.select}>
                      <SelectTrigger id={`${id}-${field.id}`} className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <FilterOptions field={field} />
                    </Select>
                  </div>
                ))}
              </div>
              <div className="flex shrink-0 items-center justify-between gap-2 px-4 pt-4 pb-4-safe">
                <Button type="button" variant="ghost" className="hover:bg-secondary" onClick={onReset}>
                  필터 초기화
                </Button>
                <SheetClose asChild>
                  <Button type="button">결과 보기</Button>
                </SheetClose>
              </div>
            </SheetContent>
          </Sheet>
        </div>

        {/* 넓을 때는 트리거가 값을 이미 보여 칩을 그리지 않는다. */}
        {appliedFields.length > 0 && (
          <div className="flex flex-wrap gap-2 @2xl:hidden">
            {appliedFields.map((field) => {
              const valueLabel = field.options.find((option) => option.value === field.value)?.label ?? field.value;
              return (
                <Button
                  key={field.id}
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-auto min-h-8 max-w-full rounded-full whitespace-normal wrap-anywhere"
                  aria-label={`${field.label} 필터 해제: ${valueLabel}`}
                  onClick={() => field.select(DEFAULT_VALUE)}
                >
                  {field.label}: {valueLabel}
                  <X aria-hidden />
                </Button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function FilterOptions({ field }: { field: FilterField }) {
  return (
    <SelectContent>
      {!!field.defaultLabel && <SelectItem value={DEFAULT_VALUE}>{field.defaultLabel}</SelectItem>}
      {field.options.map((option) => (
        <SelectItem key={option.value} value={option.value}>
          {option.label}
        </SelectItem>
      ))}
    </SelectContent>
  );
}

/** 검색은 제출만 하고 검증이 없어 zod 스키마 없이 폼 값 타입만 둔다. */
type SearchFormValues = { q: string };

function FilterSearchForm({ label, placeholder, value, onSubmit }: NonNullable<FilterBarProps["search"]>) {
  const { register, handleSubmit } = useForm<SearchFormValues>({ defaultValues: { q: value ?? "" } });

  return (
    <form
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(({ q }) => onSubmit(q.trim() || undefined))(event);
      }}
      className="flex min-w-0 flex-1 items-center gap-2 @2xl:max-w-sm @2xl:basis-56"
    >
      {/* 옆 버튼(size="sm")이 32px 라 그 높이에 맞춘다. */}
      <Input placeholder={placeholder} aria-label={label} data-filter-search className="h-8 min-w-0" {...register("q")} />
      <Button type="submit" variant="outline" size="sm">
        <Search aria-hidden className="@2xl:hidden" />
        <span className="sr-only @2xl:not-sr-only">검색</span>
      </Button>
    </form>
  );
}

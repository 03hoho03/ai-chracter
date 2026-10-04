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

/** 옵션 타입을 지워 담은 셀렉트 필터. `selectFilter` 로만 만든다. */
type SelectFilterField = {
  kind: "select";
  id: string;
  label: string;
  options: readonly FilterOption<string>[];
  value: string | undefined;
  defaultLabel?: string;
  role: "filter" | "sort";
  /** 고른 문자열을 옵션에서 다시 찾아 좁힌 뒤 넘긴다 — 못 찾으면(기본값 항목) `undefined`. */
  select: (raw: string) => void;
};

/** 시작일·종료일 한 쌍(`YYYY-MM-DD`). 둘 다 비어 있으면 기간을 거르지 않는다. */
type DateRangeFilterField = {
  kind: "date-range";
  id: string;
  /** 보이는 접두 라벨("기간"). */
  label: string;
  from?: string;
  to?: string;
  /** 바뀐 끝만 담아 부른다(시작일을 고르면 `{ from }`) — 해제 칩은 둘 다 `undefined` 로 비운다. */
  onChange: (patch: { from?: string; to?: string }) => void;
};

/** 필터 바 한 칸. 종류(`kind`)마다 모양이 다르고, 한 배열에 섞어 담는다. */
export type FilterField = SelectFilterField | DateRangeFilterField;

export function selectFilter<V extends string>({ onChange, options, role = "filter", ...rest }: SelectFilterDef<V>): FilterField {
  return {
    ...rest,
    kind: "select",
    options,
    role,
    select: (raw) => onChange(options.find((option) => option.value === raw)?.value),
  };
}

export function dateRangeFilter(def: Omit<DateRangeFilterField, "kind">): FilterField {
  return { ...def, kind: "date-range" };
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
 * - 넓을 때: 검색 + 셀렉트·기간 칸이 한 줄에서 줄바꿈된다. 트리거마다 "종류: 전체"처럼 보이는 접두 라벨이 있고 그 라벨이
 *   접근 이름이다. 값이 기본값이면 흐린 글자, 걸렸으면 진한 글자다(색이 아니라 명도로 가른다).
 * - 좁을 때: 검색 + "필터 (n)" 버튼 → 바텀시트에 라벨 + 전폭 컨트롤을 세로로 쌓고, 걸린 필터는 아래에 해제 칩으로 남는다.
 *   시트 안 변경도 즉시 적용된다(넓을 때와 같은 동작).
 */
export function FilterBar({ search, fields, onReset }: FilterBarProps) {
  const id = useId();
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const appliedFields = fields.filter(isApplied);

  return (
    <div className="@container">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* 뒤로가기 등으로 search 의 검색어가 바뀌면 폼째 리마운트해 입력칸을 맞춘다. */}
          {!!search && <FilterSearchForm key={search.value ?? ""} {...search} />}

          {fields.map((field) => (
            <InlineField key={field.id} field={field} labelId={`${id}-${field.id}-inline-label`} />
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
                  <SheetField key={field.id} field={field} controlId={`${id}-${field.id}`} />
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
              const valueLabel = appliedValueLabel(field);
              return (
                <Button
                  key={field.id}
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-auto min-h-8 max-w-full rounded-full whitespace-normal wrap-anywhere"
                  aria-label={`${field.label} 필터 해제: ${valueLabel}`}
                  onClick={() => clearField(field)}
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

/** 정렬은 목록을 줄이지 않아 "필터 (n)" 수와 해제 칩에서 빠진다. */
function isApplied(field: FilterField) {
  if (field.kind === "date-range") return field.from !== undefined || field.to !== undefined;
  return field.role === "filter" && field.value !== undefined;
}

function appliedValueLabel(field: FilterField) {
  if (field.kind === "date-range") return `${field.from ?? ""} ~ ${field.to ?? ""}`.trim();
  return field.options.find((option) => option.value === field.value)?.label ?? field.value ?? "";
}

function clearField(field: FilterField) {
  if (field.kind === "date-range") field.onChange({ from: undefined, to: undefined });
  else field.select(DEFAULT_VALUE);
}

/** 넓을 때 한 줄에 놓이는 모양. 좁을 때는 숨고 시트가 같은 값을 보여 준다. */
function InlineField({ field, labelId }: { field: FilterField; labelId: string }) {
  if (field.kind === "date-range") {
    return (
      <div role="group" aria-labelledby={labelId} className="hidden items-center gap-1.5 @2xl:flex">
        <span id={labelId} className="text-sm text-muted-foreground">
          {field.label}:
        </span>
        <DateRangeInputs field={field} className="h-8 w-auto" />
      </div>
    );
  }

  return (
    <Select value={field.value ?? DEFAULT_VALUE} onValueChange={field.select}>
      {/* 콤보박스는 내용에서 이름을 얻지 않아 보이는 접두 라벨을 `aria-labelledby` 로 이름 삼는다(값은 콤보박스
          값으로 따로 읽힌다). Radix 의 값 요소는 className 을 버려서 값 글자 명도는 트리거에서 자식 선택자로 건다. */}
      <SelectTrigger
        size="sm"
        aria-labelledby={labelId}
        className={cn(
          "hidden w-auto @2xl:flex",
          field.value === undefined
            ? "*:data-[slot=select-value]:text-muted-foreground"
            : "*:data-[slot=select-value]:font-medium",
        )}
      >
        <span id={labelId} className="text-muted-foreground">
          {field.label}:
        </span>
        <SelectValue />
      </SelectTrigger>
      <FilterOptions field={field} />
    </Select>
  );
}

/** 필터 시트 안의 모양 — 라벨이 위, 컨트롤이 전폭. */
function SheetField({ field, controlId }: { field: FilterField; controlId: string }) {
  if (field.kind === "date-range") {
    return (
      <fieldset className="flex min-w-0 flex-col gap-1.5">
        <legend className="mb-1.5 text-sm font-medium text-foreground">{field.label}</legend>
        <DateRangeInputs field={field} className="w-full" />
      </fieldset>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={controlId}>{field.label}</Label>
      <Select value={field.value ?? DEFAULT_VALUE} onValueChange={field.select}>
        <SelectTrigger id={controlId} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <FilterOptions field={field} />
      </Select>
    </div>
  );
}

/** 시작일은 종료일을, 종료일은 시작일을 넘지 못하게 서로의 값을 한계로 준다. 비우면 그 끝은 거르지 않는다. */
function DateRangeInputs({ field, className }: { field: DateRangeFilterField; className: string }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Input
        type="date"
        aria-label="시작일"
        value={field.from ?? ""}
        max={field.to}
        className={cn("min-w-0", className)}
        onChange={(event) => field.onChange({ from: event.target.value || undefined })}
      />
      <span aria-hidden className="text-sm text-muted-foreground">
        ~
      </span>
      <Input
        type="date"
        aria-label="종료일"
        value={field.to ?? ""}
        min={field.from}
        className={cn("min-w-0", className)}
        onChange={(event) => field.onChange({ to: event.target.value || undefined })}
      />
    </div>
  );
}

function FilterOptions({ field }: { field: SelectFilterField }) {
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

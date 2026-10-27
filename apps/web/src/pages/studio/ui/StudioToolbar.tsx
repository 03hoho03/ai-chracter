import type { RefObject } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";

import { MyWorksSearchField } from "@/entities/work";

import {
  isStudioStatusFilter,
  isStudioTypeFilter,
  STUDIO_STATUS_FILTERS,
  STUDIO_TYPE_FILTERS,
  type StudioSearch,
  type StudioStatusFilter,
  type StudioTypeFilter,
} from "../model/studioSearch";

export const STUDIO_TYPE_FILTER_LABEL: Record<StudioTypeFilter, string> = {
  all: "전체",
  character: "캐릭터",
  story: "스토리",
  novel: "소설",
};

export const STUDIO_STATUS_FILTER_LABEL: Record<StudioStatusFilter, string> = {
  all: "전체",
  draft: "초안",
  public: "공개 중",
  changed: "수정본 있음",
  review: "심사 중",
};

/** 상태가 좁혀지지 않았을 때 트리거에 띄우는 축 이름. 값 이름 "전체"를 그대로 두면 옆 칩의 "전체"와 같은 낱말이 한 줄에
 * 둘이라 어느 축의 전체인지 갈리지 않는다. */
const STATUS_AXIS_LABEL = "상태";

/** 소설 영역이 닫힌 계정에는 소설 칩과 "심사 중"(소설에만 있는 상태)이 없다. */
export function toStudioTypeOptions(isNovelAreaVisible: boolean): StudioTypeFilter[] {
  return STUDIO_TYPE_FILTERS.filter((value) => isNovelAreaVisible || value !== "novel");
}

function toStudioStatusOptions(isNovelAreaVisible: boolean): StudioStatusFilter[] {
  return STUDIO_STATUS_FILTERS.filter((value) => isNovelAreaVisible || value !== "review");
}

type StudioToolbarProps = {
  typeFilterRef: RefObject<HTMLDivElement | null>;
  searchInputRef: RefObject<HTMLInputElement | null>;
  type: StudioTypeFilter;
  status: StudioStatusFilter;
  q: string | undefined;
  isNovelAreaVisible: boolean;
  /** 묶음 화면에는 상태 셀렉트가 없다 — 묶음은 내가 고른 작품 몇 개라 상태로 다시 거를 일이 적고, 줄이 짧아진다. */
  isStatusFilterVisible: boolean;
  onSearchChange: (patch: Partial<StudioSearch>) => void;
};

/**
 * 유형 칩 · 상태 셀렉트 · 제목 검색. 흐름 안의 줄이라 sticky 가 아니고, 폭이 모자라면 다음 줄로 접는다(390px 에서는
 * 칩+셀렉트 / 검색 전체 폭). 칩·셀렉트는 손가락 포인터에서 40px 로 키운다.
 *
 * 유형이 칩이고 상태가 셀렉트인 이유: 유형은 넷이 한 줄에 들어가지만 상태 다섯까지 칩으로 두면 좁은 폭에서 두 줄이 된다.
 * 칩은 단일선택 `ToggleGroup`(선택 상태는 프리미티브가 정한다)이고, 걸린 상태 셀렉트는 내 작품 화면의 공개 여부
 * 셀렉트와 같이 `ring` 윤곽으로 켜짐을 보인다 — 채움을 늘리지 않고, 꺼진 칩처럼 보이지 않게.
 */
export function StudioToolbar({
  typeFilterRef,
  searchInputRef,
  type,
  status,
  q,
  isNovelAreaVisible,
  isStatusFilterVisible,
  onSearchChange,
}: StudioToolbarProps) {
  return (
    <div className="-m-1 flex flex-wrap items-center gap-x-6 gap-y-3 p-1">
      <ToggleGroup
        ref={typeFilterRef}
        type="single"
        variant="outline"
        size="sm"
        value={type}
        onValueChange={(value) => {
          if (!isStudioTypeFilter(value)) return;
          onSearchChange({ type: value === "all" ? undefined : value });
        }}
        aria-label="작품 유형 필터"
        className="shrink-0"
      >
        {toStudioTypeOptions(isNovelAreaVisible).map((value) => (
          <ToggleGroupItem key={value} value={value} data-filter={value} className="pointer-coarse:h-10">
            {STUDIO_TYPE_FILTER_LABEL[value]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {isStatusFilterVisible && (
        <Select
          value={status}
          onValueChange={(value) => {
            if (!isStudioStatusFilter(value)) return;
            onSearchChange({ status: value === "all" ? undefined : value });
          }}
        >
          {/* 트리거 안에는 `SelectValue` 가 있어야 Radix 가 열린 목록으로 포커스를 옮긴다. 축 이름은 `aria-label` 로 함께
              넘긴다(`aria-label` 이 내용을 덮으므로 값도 같이 담는다). */}
          <SelectTrigger
            size="sm"
            className={cn("shrink-0 pointer-coarse:h-10", status === "all" ? "text-muted-foreground" : "border-ring")}
            aria-label={status === "all" ? STATUS_AXIS_LABEL : `${STATUS_AXIS_LABEL}: ${STUDIO_STATUS_FILTER_LABEL[status]}`}
          >
            <SelectValue>{status === "all" ? STATUS_AXIS_LABEL : STUDIO_STATUS_FILTER_LABEL[status]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {toStudioStatusOptions(isNovelAreaVisible).map((value) => (
              <SelectItem key={value} value={value}>
                {STUDIO_STATUS_FILTER_LABEL[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <MyWorksSearchField
        inputRef={searchInputRef}
        query={q}
        onQueryChange={(next) => onSearchChange({ q: next })}
        className="ml-auto min-w-0 flex-1 basis-56 sm:max-w-72"
      />
    </div>
  );
}

/** 걸린 유형·상태를 이름으로 적는다(`캐릭터 · 초안`). 아무것도 안 걸렸으면 `undefined`. */
export function describeStudioFilter(type: StudioTypeFilter, status: StudioStatusFilter): string | undefined {
  const axes: string[] = [];
  if (type !== "all") axes.push(STUDIO_TYPE_FILTER_LABEL[type]);
  if (status !== "all") axes.push(STUDIO_STATUS_FILTER_LABEL[status]);
  return axes.length === 0 ? undefined : axes.join(" · ");
}

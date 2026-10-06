import { cn } from "@ai-character-chat/ui/lib/utils";
import { GripVertical, ImageIcon } from "lucide-react";

import { ENDING_RULE_OPERATOR_SYMBOLS, STAT_ICON_OPTIONS } from "@/entities/chat-room";
import { countCharacters, STORY_FIELD_LABELS, type FieldLabel, type StoryFieldKey } from "@/features/build-story";
import { assertNever } from "@/shared/lib/assertNever";

import { findGuideImage } from "../config/guideImages";
import type { GuideMockupContext } from "../model/guideMockupContext";
import { isStoryFieldKey } from "../model/mockupCaption";
import { choicesOf, logicOpChoices, selectLabelOf } from "../model/mockupChoices";
import { isRecord, parseMockupValue, type MockupValue } from "../model/mockupValue";
import type { FieldValue } from "../model/parseManuscript";
import { GuideCardListMockup } from "./GuideCardListMockup";
import { GuideMediaGridMockup } from "./GuideMediaGridMockup";
import {
  MockupChoiceChips,
  MockupInput,
  MockupLabel,
  MockupSelect,
  MockupSwitch,
  MockupTextarea,
  MockupValueChips,
} from "./GuideMockupControls";

/** 빌더에서 값이 칩으로 쌓이기 전에 입력칸이 먼저 있는 칸. 그림도 입력칸 + 칩으로 그린다. */
const CHIP_INPUT_KEYS: ReadonlySet<string> = new Set([
  "keywordNotes.*.triggerKeywords",
  "keywordNotes.*.excludeKeywords",
  "registration.hashtags",
]);

const STAT_ICON_KEY = "startingSetups.*.stats.*.icon";
const STAT_COLOR_KEY = "startingSetups.*.stats.*.color";
const STAT_NAME_KEY = "startingSetups.*.stats.*.name";

type GuideFieldMockupsProps = {
  values: readonly FieldValue[];
  context: GuideMockupContext;
  /** false 면 여러 줄 칸을 자르지 않는다(대비 발췌). */
  clampsLongText?: boolean;
};

/**
 * 칸 값 여러 개를 빌더 칸 모양으로 쌓는다. 빌더가 한 줄에 놓는 칸 묶음(스탯의 아이콘·색·이름, 수치 칸들)은 같은 줄
 * 배치로 그린다 — 따로 쌓으면 빌더에서 본 모양과 달라 "그 칸"으로 읽히지 않는다.
 */
export function GuideFieldMockups({ values, context, clampsLongText = true }: GuideFieldMockupsProps) {
  const keys = values.map((value) => value.key);
  if (keys.includes(STAT_ICON_KEY)) return <StatIdentityMockup values={values} />;
  const isNumberRow = values.length > 1 && values.every((value) => kindOf(value.key, context) === "number");

  return (
    <div className={cn("grid gap-3", isNumberRow && "grid-cols-3")}>
      {values.map((value) => (
        <GuideFieldMockup key={value.key} value={value} context={context} clampsLongText={clampsLongText} />
      ))}
    </div>
  );
}

type GuideFieldMockupProps = {
  value: FieldValue;
  context: GuideMockupContext;
  clampsLongText: boolean;
};

function GuideFieldMockup({ value, context, clampsLongText }: GuideFieldMockupProps) {
  const { key } = value;
  if (!isStoryFieldKey(key)) throw new Error(`라벨 상수에 없는 칸 키: ${key}`);
  const mockup = context.mockups[key];
  const parsed = parseMockupValue(mockup.kind, value.body);

  if (parsed.kind === "switch") {
    return (
      <div className="flex min-h-9 items-center justify-between gap-4">
        <MockupLabel fieldKey={key} />
        <MockupSwitch isOn={parsed.value} />
      </div>
    );
  }

  const counter =
    mockup.counter && mockup.limit !== undefined && (parsed.kind === "text" || parsed.kind === "textarea")
      ? `${countCharacters(parsed.text)}/${mockup.limit}`
      : null;

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <MockupLabel fieldKey={key} />
        {counter && <span className="text-xs text-muted-foreground tabular-nums">{counter}</span>}
      </div>
      <MockupControl fieldKey={key} parsed={parsed} context={context} clampsLongText={clampsLongText} />
    </div>
  );
}

type MockupControlProps = {
  fieldKey: StoryFieldKey;
  parsed: MockupValue;
  context: GuideMockupContext;
  clampsLongText: boolean;
};

function MockupControl({ fieldKey, parsed, context, clampsLongText }: MockupControlProps) {
  switch (parsed.kind) {
    case "text":
      return <MockupInput value={parsed.text} placeholder={placeholderOf(fieldKey)} />;
    case "textarea":
      return <MockupTextarea text={parsed.text} clampsLongText={clampsLongText} />;
    case "number":
      return <MockupInput value={String(parsed.value)} />;
    case "select":
      return <MockupSelect value={selectLabelOf(fieldKey, parsed.value)} className="w-fit min-w-40" />;
    case "toggle":
      return <MockupChoiceChips choices={choicesOf(fieldKey, parsed.value)} />;
    case "chips":
      return (
        <div className="flex flex-col gap-2">
          {CHIP_INPUT_KEYS.has(fieldKey) && <MockupInput value="" placeholder={placeholderOf(fieldKey)} />}
          <MockupValueChips items={parsed.items} />
        </div>
      );
    case "image":
      return <CoverWell token={parsed.token} />;
    case "statRules":
      return <StatRulesMockup rules={parsed.rules} />;
    case "cardList":
      return <GuideCardListMockup listKey={fieldKey} cards={parsed.cards} more={parsed.more} />;
    case "mediaGrid":
      return <MediaGridControl parsed={parsed} context={context} />;
    case "icon":
    case "color":
    case "switch":
      // 아이콘·색은 이름 칸과 한 줄로(`StatIdentityMockup`), 스위치는 라벨 옆 줄로 그린다.
      throw new Error(`따로 그리는 칸 모양이 칸 하나로 왔다: ${fieldKey}`);
    default:
      return assertNever(parsed);
  }
}

function kindOf(key: string, context: GuideMockupContext) {
  return isStoryFieldKey(key) ? context.mockups[key].kind : null;
}

function placeholderOf(key: StoryFieldKey): string | undefined {
  const label: FieldLabel = STORY_FIELD_LABELS[key];
  return label.placeholder;
}

/** 대표 이미지 칸 — 빌더 프로필 웰과 같은 크기(가로 112px, 2:3)·같은 면. 업로드·생성 버튼은 누를 것처럼 보여 그리지 않는다. */
function CoverWell({ token }: { token: string }) {
  const image = findGuideImage(token);
  return (
    <div className="flex aspect-story w-28 items-center justify-center overflow-hidden rounded-lg bg-muted">
      {image ? (
        // 그림이 무엇인지는 액자 캡션과 블록 설명이 이미 말해 대체 글을 비운다.
        <img
          src={image.src}
          width={image.width}
          height={image.height}
          alt=""
          loading="lazy"
          decoding="async"
          className="size-full object-cover"
        />
      ) : (
        <ImageIcon aria-hidden className="size-5 text-muted-foreground" />
      )}
    </div>
  );
}

/** 스탯 모양 줄 — 빌더처럼 아이콘·색 버튼과 이름 칸이 한 줄이고 라벨은 이름 칸 위에만 있다. */
function StatIdentityMockup({ values }: { values: readonly FieldValue[] }) {
  const bodyOf = (key: string) => values.find((value) => value.key === key)?.body ?? "";
  const icon = parseMockupValue("icon", bodyOf(STAT_ICON_KEY));
  const color = parseMockupValue("color", bodyOf(STAT_COLOR_KEY));
  const iconOption = STAT_ICON_OPTIONS.find((option) => option.name === (icon.kind === "icon" ? icon.value : ""));
  const colorValue = color.kind === "color" ? color.value : "";

  return (
    <div className="grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-x-2 gap-y-1.5">
      <span className="col-start-3">
        <MockupLabel fieldKey={STAT_NAME_KEY} />
      </span>
      <span className="flex size-9 items-center justify-center rounded-lg border border-input text-foreground">
        {iconOption && <iconOption.Icon aria-hidden className="size-4" />}
        <span className="sr-only">{`${STORY_FIELD_LABELS[STAT_ICON_KEY].label}: ${iconOption?.label ?? ""}`}</span>
      </span>
      <span className="flex size-9 items-center justify-center rounded-lg border border-input">
        {/* 스탯 색은 작가가 고른 값이라 토큰이 아니다. */}
        <span aria-hidden className="size-4 rounded-full" style={{ backgroundColor: colorValue }} />
        <span className="sr-only">{STORY_FIELD_LABELS[STAT_COLOR_KEY].label}</span>
      </span>
      <MockupInput value={bodyOf(STAT_NAME_KEY)} />
    </div>
  );
}

/** 엔딩의 스탯 기반 규칙 줄. 원고 값은 시드(서버) 표기라 연산자를 빌더 화면의 기호로 바꿔 그린다. 이웃한 두 항목 사이에는
 * 빌더처럼 관계(그리고/또는)를 그리고, 마지막 항목 뒤에는 그리지 않는다 — 그 `nextOp` 는 평가에서 쓰이지 않는다. 그룹은
 * 빌더에서 접힌 채로 보이는 머리 줄만 그려 그 안의 관계는 그리지 않는다. */
function StatRulesMockup({ rules }: { rules: readonly Record<string, unknown>[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {rules.map((rule, index) => (
        // 원고에서 온 고정 목록이라 순서가 바뀌지 않는다.
        <li key={index} className="flex flex-col gap-2">
          <div className="flex items-center gap-2 rounded-lg border border-border p-3">
            <GripVertical aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            {rule.kind === "group" ? (
              <span className="text-sm font-semibold text-foreground">
                규칙 그룹{" "}
                <span className="text-xs font-normal text-muted-foreground">
                  조건 {Array.isArray(rule.rules) ? rule.rules.filter(isRecord).length : 0}개
                </span>
              </span>
            ) : (
              <div className="@container min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <MockupSelect value={typeof rule.stat === "string" ? rule.stat : ""} className="w-full @xs:w-32" />
                  <MockupSelect value={operatorSymbol(rule.operator)} className="w-20 shrink-0" />
                  <MockupInput
                    value={typeof rule.threshold === "number" ? String(rule.threshold) : ""}
                    className="w-24 shrink-0"
                  />
                </div>
              </div>
            )}
          </div>
          {index < rules.length - 1 && (
            <MockupChoiceChips choices={logicOpChoices(rule.nextOp)} size="sm" className="ml-7" />
          )}
        </li>
      ))}
    </ul>
  );
}

function operatorSymbol(operator: unknown): string {
  const entry = Object.entries(ENDING_RULE_OPERATOR_SYMBOLS).find(([apiOperator]) => apiOperator === operator);
  if (!entry) throw new Error(`모르는 연산자: ${String(operator)}`);
  return entry[1];
}

type MediaGridControlProps = {
  parsed: Extract<MockupValue, { kind: "mediaGrid" }>;
  context: GuideMockupContext;
};

function MediaGridControl({ parsed, context }: MediaGridControlProps) {
  const people = parseMockupValue("chips", context.valueOf("mediaBook.people") ?? "[]");
  const scenes = parseMockupValue("chips", context.valueOf("mediaBook.scenes") ?? "[]");
  return (
    <GuideMediaGridMockup
      people={people.kind === "chips" ? people.items : []}
      scenes={scenes.kind === "chips" ? scenes.items : []}
      cells={parsed.cells}
      selected={parsed.selected}
    />
  );
}

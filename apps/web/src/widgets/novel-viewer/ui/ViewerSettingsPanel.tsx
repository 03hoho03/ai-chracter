import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useAtom } from "jotai";
import { Moon, Sun } from "lucide-react";
import { useId, type ReactNode, type Ref } from "react";

import { isTheme, themeAtom } from "@/shared/model/theme";

import {
  readerSettingsAtom,
  READER_FONT_SIZES,
  READER_LINE_HEIGHTS,
  READER_MARGINS,
  type ReaderFontSize,
  type ReaderLineHeight,
  type ReaderMargin,
} from "../model/readerSettings";

const FONT_SIZE_LABEL = { small: "보통", medium: "크게", large: "더 크게" } satisfies Record<ReaderFontSize, string>;
const LINE_HEIGHT_LABEL = { normal: "좁게", relaxed: "보통", loose: "넓게" } satisfies Record<ReaderLineHeight, string>;
const MARGIN_LABEL = { narrow: "좁게", medium: "보통", wide: "넓게" } satisfies Record<ReaderMargin, string>;

/** 목록 안의 값인지 확인하며 좁힌다. Radix 단일 선택 토글은 이미 고른 칸을 다시 누르면 빈 문자열을 내므로, 그때는
 * 무시해 언제나 하나가 선택된 상태를 지킨다. */
function pick<T extends string>(options: readonly T[], value: string): T | undefined {
  return options.find((option) => option === value);
}

/**
 * 보기 설정 — 글자 크기·줄 간격·여백·테마. 아래 바 위에 붙어 열리는 **비모달** 패널이다: 본문을 흐리거나 가리지 않아
 * 바꾼 설정이 바로 본문에 보이고, 포커스를 가두지 않는다(시트는 늘 흐린 막을 함께 그려 고르는 동안 결과를 볼 수
 * 없다). 고른 칩은 `primary` 채움이 아니라 무채 표면 + 윤곽이다 — 네 줄이 동시에 선택돼 있어, 채우면 한 화면에 솔리드
 * 채움이 넷이 된다(밝기 예산).
 *
 * 글자 크기 첫 칸을 "보통"이라 부르는 것은 그것이 기본값이라서다 — "작게"로 부르면 기본이 작은 글씨처럼 읽힌다.
 * 테마는 이 화면만의 값이 아니라 앱 전체 테마다(다크 변형이 문서 전체에 걸려 화면 하나만 따로 둘 수 없다).
 */
export function ViewerSettingsPanel({ ref, id }: { ref: Ref<HTMLDivElement>; id: string }) {
  const [settings, setSettings] = useAtom(readerSettingsAtom);
  const [theme, setTheme] = useAtom(themeAtom);

  return (
    <div
      ref={ref}
      id={id}
      role="group"
      aria-label="보기 설정"
      className="flex flex-col gap-3 border-t border-border bg-popover px-4 py-4 sm:px-6"
    >
      <SettingRow label="글자 크기">
        {(labelId) => (
          <ToggleGroup
            type="single"
            variant="neutral"
            size="sm"
            aria-labelledby={labelId}
            value={settings.fontSize}
            onValueChange={(value) => {
              const fontSize = pick(READER_FONT_SIZES, value);
              if (fontSize !== undefined) setSettings((prev) => ({ ...prev, fontSize }));
            }}
          >
            {READER_FONT_SIZES.map((option) => (
              <ToggleGroupItem key={option} value={option}>
                {FONT_SIZE_LABEL[option]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </SettingRow>
      <SettingRow label="줄 간격">
        {(labelId) => (
          <ToggleGroup
            type="single"
            variant="neutral"
            size="sm"
            aria-labelledby={labelId}
            value={settings.lineHeight}
            onValueChange={(value) => {
              const lineHeight = pick(READER_LINE_HEIGHTS, value);
              if (lineHeight !== undefined) setSettings((prev) => ({ ...prev, lineHeight }));
            }}
          >
            {READER_LINE_HEIGHTS.map((option) => (
              <ToggleGroupItem key={option} value={option}>
                {LINE_HEIGHT_LABEL[option]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </SettingRow>
      <SettingRow label="여백">
        {(labelId) => (
          <ToggleGroup
            type="single"
            variant="neutral"
            size="sm"
            aria-labelledby={labelId}
            value={settings.margin}
            onValueChange={(value) => {
              const margin = pick(READER_MARGINS, value);
              if (margin !== undefined) setSettings((prev) => ({ ...prev, margin }));
            }}
          >
            {READER_MARGINS.map((option) => (
              <ToggleGroupItem key={option} value={option}>
                {MARGIN_LABEL[option]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </SettingRow>
      <SettingRow label="테마" hint="앱 전체에 적용돼요">
        {(labelId, hintId) => (
          <ToggleGroup
            type="single"
            variant="neutral"
            size="sm"
            aria-labelledby={labelId}
            aria-describedby={hintId}
            value={theme}
            onValueChange={(value) => {
              if (isTheme(value)) setTheme(value);
            }}
          >
            <ToggleGroupItem value="dark">
              <Moon aria-hidden />
              다크
            </ToggleGroupItem>
            <ToggleGroupItem value="light">
              <Sun aria-hidden />
              라이트
            </ToggleGroupItem>
          </ToggleGroup>
        )}
      </SettingRow>
    </div>
  );
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: (labelId: string, hintId: string | undefined) => ReactNode;
}) {
  const labelId = useId();
  const hintId = useId();

  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-4">
      <span id={labelId} className="w-16 shrink-0 text-xs font-medium text-muted-foreground">
        {label}
      </span>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {children(labelId, hint === undefined ? undefined : hintId)}
        {hint !== undefined && (
          <span id={hintId} className="text-xs text-muted-foreground">
            {hint}
          </span>
        )}
      </div>
    </div>
  );
}

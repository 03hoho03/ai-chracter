import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { onOffText, switchLabelOf } from "../model/switchCopy";
import type { AdminUnknownOverride } from "../model/types";
import { ClearOverrideDialog } from "./ClearOverrideDialog";
import { UNKNOWN_OVERRIDES_HEADING_ID } from "./elementIds";
import { FOCUS_TARGET_HEADING_CLASS, SECTION_CARD_CLASS } from "./styles";

type UnknownOverrideSectionProps = {
  overrides: readonly AdminUnknownOverride[];
  refreshSeconds: number;
  meId: string | undefined;
};

/** 지금 서버 판이 버튼으로 다루지 않는 이름의 덮어쓰기 행(다른 판이 남긴 행). 있을 때만 그린다. */
export function UnknownOverrideSection({ overrides, refreshSeconds, meId }: UnknownOverrideSectionProps) {
  return (
    <section aria-labelledby={UNKNOWN_OVERRIDES_HEADING_ID} className={SECTION_CARD_CLASS}>
      <div className="flex flex-col gap-1">
        <h2
          id={UNKNOWN_OVERRIDES_HEADING_ID}
          tabIndex={-1}
          className={cn("break-keep text-lg font-semibold text-foreground", FOCUS_TARGET_HEADING_CLASS)}
        >
          이 이미지가 모르는 덮어쓰기
        </h2>
        <p className="max-w-prose text-sm break-keep text-muted-foreground">
          지금 이미지가 버튼으로 다루지 않는 이름의 덮어쓰기예요. 지금은 무시되고 그 스위치는 .env 값으로 돌아요. 이 이름을
          버튼으로 다루던 판으로 되돌리면 다시 살아나요 — 남길 이유가 없으면 지우세요.
        </p>
      </div>
      <ul className="flex flex-col">
        {overrides.map((override) => {
          const label = switchLabelOf(override.name);
          return (
            <li
              key={override.name}
              className="flex flex-col gap-2 border-t border-border py-3 first:border-t-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
            >
              <div className="flex min-w-0 flex-col gap-0.5 text-sm">
                {label !== null && <span className="font-semibold text-foreground">{label}</span>}
                <code className="font-sans text-xs wrap-anywhere text-muted-foreground">{override.name}</code>
                <span className="break-all text-foreground">
                  덮어쓴 값 {onOffText(override.value)}
                  <span className="text-muted-foreground">
                    {" "}
                    · {override.adminId === meId ? "나" : override.adminEmail} · {formatDateTime(override.updatedAt)}
                  </span>
                </span>
              </div>
              {/* 카드 위에서는 ghost 의 `hover:bg-muted` 가 카드와 같은 값이라 사라진다 — 한 칸 진한 면으로 덮는다. */}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="self-start hover:bg-secondary sm:self-center"
                onClick={() => void ClearOverrideDialog.call({ kind: "unknown", override, refreshSeconds })}
              >
                <span className="sr-only">{label ?? override.name} </span>
                지우기…
              </Button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

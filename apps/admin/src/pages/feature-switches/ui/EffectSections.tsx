import { Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import type { ResolvedEffects } from "../model/switchEffects";

/** 확인 모달의 "바뀌는 것"과 경고·되돌릴 수 없는 것·알아 둘 것. 경고는 색이 아니라 아이콘과 글자로 가른다. */
export function EffectSections({ effects }: { effects: ResolvedEffects }) {
  return (
    <>
      <EffectList title="바뀌는 것" lines={effects.changes} />
      {effects.warnings.map((warning) => (
        <NoticeLine key={warning} kind="warning">
          {warning}
        </NoticeLine>
      ))}
      {effects.irreversible.length > 0 && <EffectList title="되돌릴 수 없는 것" lines={effects.irreversible} />}
      {effects.notes.length > 0 && <EffectList title="알아 둘 것" lines={effects.notes} />}
    </>
  );
}

function EffectList({ title, lines }: { title: string; lines: readonly string[] }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-foreground">
        {lines.map((line) => (
          // 코드 이름(IDENTITY_VERIFICATION_REQUIRED 등)·설정 키 이름이 좁은 모달 폭을 넘지 않게 그 자리에서만 끊는다.
          <li key={line} className="break-keep wrap-anywhere">
            {line}
          </li>
        ))}
      </ul>
    </section>
  );
}

type NoticeLineProps = {
  /** `warning` 은 지금 값 때문에 생기는 주의(효과 없음·선행 조건), `info` 는 알려 두기만 하는 사실. */
  kind: "warning" | "info";
  children: ReactNode;
};

export function NoticeLine({ kind, children }: NoticeLineProps) {
  const Icon = kind === "warning" ? TriangleAlert : Info;
  return (
    <p className="flex gap-2 text-sm break-keep text-foreground">
      <Icon aria-hidden className="mt-1 size-4 shrink-0" />
      <span className="min-w-0 wrap-anywhere">{children}</span>
    </p>
  );
}

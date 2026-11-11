import type { ReactNode } from "react";

import { cn } from "@/shared/lib/cn";
import type { Crumb } from "@/widgets/app-shell";

/** 헤더 빵부스러기 — `런` 다음에 고른 폴더의 마디마다 한 칸. 누르면 그 폴더로 간다. */
export function folderCrumbs(folder: string, onSelect: (path: string) => void): Crumb[] {
  const names = folder === "" ? [] : folder.split("/");
  return [
    {
      key: "",
      content: (
        <CrumbButton isCurrent={names.length === 0} onClick={() => onSelect("")}>
          런
        </CrumbButton>
      ),
    },
    ...names.map((name, index) => {
      const path = names.slice(0, index + 1).join("/");
      return {
        key: path,
        content: (
          <CrumbButton isMono isCurrent={index === names.length - 1} onClick={() => onSelect(path)}>
            {name}
          </CrumbButton>
        ),
      };
    }),
  ];
}

type CrumbButtonProps = {
  isCurrent: boolean;
  isMono?: boolean;
  onClick: () => void;
  children: ReactNode;
};

function CrumbButton({ isCurrent, isMono = false, onClick, children }: CrumbButtonProps) {
  return (
    <button
      type="button"
      aria-current={isCurrent ? "location" : undefined}
      onClick={onClick}
      className={cn(
        "max-w-full truncate rounded-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        isMono ? "font-mono text-data" : "text-body",
        isCurrent ? "font-semibold text-ink" : "text-ink-secondary hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

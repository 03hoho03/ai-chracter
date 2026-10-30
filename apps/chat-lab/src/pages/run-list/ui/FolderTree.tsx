import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/formatNumber";

import type { FolderNode } from "../model/folderTree";

type FolderTreeProps = {
  root: FolderNode;
  selectedFolder: string;
  isExpanded: (node: FolderNode) => boolean;
  onToggle: (node: FolderNode) => void;
  onSelect: (path: string) => void;
};

/** 왼쪽 폴더 트리. 칸을 고르면 가운데 표가 그 폴더 아래 런으로 바뀐다. */
export function FolderTree({ root, selectedFolder, isExpanded, onToggle, onSelect }: FolderTreeProps) {
  return (
    <ul className="py-1">
      <FolderTreeItem
        node={root}
        depth={0}
        selectedFolder={selectedFolder}
        isExpanded={isExpanded}
        onToggle={onToggle}
        onSelect={onSelect}
      />
    </ul>
  );
}

type FolderTreeItemProps = Omit<FolderTreeProps, "root"> & { node: FolderNode; depth: number };

function FolderTreeItem({ node, depth, selectedFolder, isExpanded, onToggle, onSelect }: FolderTreeItemProps) {
  const hasChildren = node.children.length > 0;
  const isOpen = hasChildren && isExpanded(node);
  const isSelected = node.path === selectedFolder;
  const isRoot = node.path === "";

  return (
    <li>
      <div
        // 들여쓰기 폭은 깊이에 따라 달라지는 실행 중 값이다.
        style={{ paddingLeft: 4 + depth * 12 }}
        className={cn(
          "flex h-7 items-center pr-2 text-data motion-safe:transition-colors",
          isSelected ? "bg-surface-raised" : "hover:bg-surface-raised",
        )}
      >
        {hasChildren ? (
          <button
            type="button"
            aria-expanded={isOpen}
            aria-label={`${isRoot ? "전체" : node.label} ${isOpen ? "접기" : "펼치기"}`}
            onClick={() => onToggle(node)}
            className="flex size-5 shrink-0 items-center justify-center rounded-sm text-label text-ink-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
          </button>
        ) : (
          <span className="size-5 shrink-0" />
        )}
        <button
          type="button"
          aria-current={isSelected ? "location" : undefined}
          title={isRoot ? "런 루트 전체" : node.path}
          onClick={() => onSelect(node.path)}
          className="flex h-full min-w-0 flex-1 items-center gap-2 rounded-sm pl-1 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
        >
          <span
            className={cn(
              "truncate",
              !isRoot && "font-mono",
              isSelected ? "font-semibold text-ink" : "text-ink-secondary",
            )}
          >
            {node.label}
          </span>
          <span className="ml-auto shrink-0 text-ink-muted tabular-nums">{formatCount(node.runCount)}</span>
        </button>
      </div>
      {isOpen && (
        <ul>
          {node.children.map((child) => (
            <FolderTreeItem
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedFolder={selectedFolder}
              isExpanded={isExpanded}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

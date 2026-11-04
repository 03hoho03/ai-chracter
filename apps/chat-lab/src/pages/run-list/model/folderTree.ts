import { compareText } from "@/shared/lib/compareText";

/** 폴더 트리의 한 칸. 뿌리는 `path` 가 빈 글이고 런 루트 전체다. */
export type FolderNode = {
  /** 런 루트 기준 폴더 경로. 합친 칸이면 가장 깊은 폴더의 경로다. */
  path: string;
  /** 트리에 적는 이름. 런 없이 폴더 하나만 품은 폴더를 합치면 `s3/probes` 처럼 이어 적는다. */
  label: string;
  /** 측정 서버가 그룹으로 접는 대량 시도 폴더 자체인가. */
  isBulk: boolean;
  /** 대량 시도 폴더이거나 그 안인가 — 이런 칸은 접힌 채 시작한다. */
  isInBulk: boolean;
  /** 이 폴더 아래(하위 폴더 포함) 런 수. */
  runCount: number;
  children: FolderNode[];
};

/** 트리가 보는 런의 칸. `group` 은 측정 서버가 대량 시도 폴더 아래 런에 붙이는 그 폴더까지의 경로다. */
type FolderRun = {
  path: string;
  group: string | null;
};

type DraftFolder = {
  path: string;
  name: string;
  runCount: number;
  children: Map<string, DraftFolder>;
};

/**
 * 런 경로(런 루트 기준 드라이버 로그 경로)를 폴더 트리로 묶는다.
 *
 * - 런이 하나뿐인 폴더는 트리에 따로 두지 않는다. 실데이터에서 대량 시도 폴더 밖 폴더 대부분이 런 하나짜리라, 그것까지 두면
 *   트리가 런 목록을 한 번 더 적는 꼴이 된다. 그 런은 부모 폴더의 표에서 한 행이다.
 * - 런 없이 폴더 하나만 품은 폴더는 그 폴더와 한 칸으로 합친다(`s3/probes`) — 눌러 봐야 한 칸 더 내려갈 뿐인 칸을 없앤다.
 * - 대량 시도 폴더는 런이 하나여도 남기고(그 폴더를 품은 런 하나짜리 폴더도 함께), 아래 칸과 합치지 않는다. 표가 그 폴더를
 *   그룹 행으로 접는 경계라 트리에서 사라지면 그 안으로 들어갈 길이 없다.
 */
export function buildFolderTree(runs: ReadonlyArray<FolderRun>): FolderNode {
  const bulkFolders = new Set(runs.flatMap((run) => (run.group === null ? [] : [run.group])));
  const root: DraftFolder = { path: "", name: "", runCount: 0, children: new Map() };

  for (const run of runs) {
    root.runCount += 1;
    let parent = root;
    for (const name of run.path.split("/").slice(0, -1)) {
      const path = parent.path === "" ? name : `${parent.path}/${name}`;
      const child = parent.children.get(name) ?? { path, name, runCount: 0, children: new Map<string, DraftFolder>() };
      child.runCount += 1;
      parent.children.set(name, child);
      parent = child;
    }
  }

  return {
    path: "",
    label: "전체",
    isBulk: false,
    isInBulk: false,
    runCount: root.runCount,
    children: visibleChildren(root, bulkFolders),
  };
}

/**
 * 트리에서 이 칸이 펼쳐져 있는가. 손으로 펼치거나 접은 값(`overrides`)이 있으면 그것이 이기고, 없으면 대량 시도 폴더와 그 아래는
 * 접힘, 나머지는 펼침이다 — 대량 시도 폴더 하나에 하위 폴더가 수십~수백 개라 펼친 채로 시작하면 트리가 그것으로 덮인다.
 */
export function isFolderExpanded(node: FolderNode, overrides: ReadonlyMap<string, boolean>): boolean {
  return overrides.get(node.path) ?? !node.isInBulk;
}

/** `path` 의 폴더 칸. 트리에 없는 폴더(런 하나짜리·합쳐진 중간 폴더)면 undefined. */
export function findFolder(node: FolderNode, path: string): FolderNode | undefined {
  if (node.path === path) return node;
  for (const child of node.children) {
    const found = findFolder(child, path);
    if (found) return found;
  }
  return undefined;
}

/** `path` 가 `folder` 자신이거나 그 아래인가. 뿌리(빈 글)는 모든 경로를 품는다. 이름 앞부분만 같은 옆 폴더는 아니다. */
export function isWithinFolder(path: string, folder: string): boolean {
  return folder === "" || path === folder || path.startsWith(`${folder}/`);
}

/** 고른 폴더를 앞에서 뗀 경로 — 표의 경로 칸이 짧아진다. */
export function relativeToFolder(path: string, folder: string): string {
  return folder !== "" && path.startsWith(`${folder}/`) ? path.slice(folder.length + 1) : path;
}

/** 뿌리 다음부터 자기 자신 앞까지의 폴더 경로. 트리에서 그 폴더가 보이도록 펼칠 칸들이다. */
export function ancestorFolders(path: string): string[] {
  const names = path === "" ? [] : path.split("/");
  return names.slice(0, -1).map((_, index) => names.slice(0, index + 1).join("/"));
}

function visibleChildren(draft: DraftFolder, bulkFolders: ReadonlySet<string>): FolderNode[] {
  return [...draft.children.values()]
    .filter((child) => child.runCount > 1 || holdsBulkFolder(child.path, bulkFolders))
    .map((child) => toFolderNode(child, bulkFolders))
    .sort((a, b) => compareText(a.label, b.label));
}

/** 이 폴더가 대량 시도 폴더이거나 그것을 품는가. */
function holdsBulkFolder(path: string, bulkFolders: ReadonlySet<string>): boolean {
  return [...bulkFolders].some((bulk) => bulk === path || bulk.startsWith(`${path}/`));
}

function toFolderNode(draft: DraftFolder, bulkFolders: ReadonlySet<string>): FolderNode {
  const isBulk = bulkFolders.has(draft.path);
  const node: FolderNode = {
    path: draft.path,
    label: draft.name,
    isBulk,
    isInBulk: isBulk || [...bulkFolders].some((bulk) => draft.path.startsWith(`${bulk}/`)),
    runCount: draft.runCount,
    children: visibleChildren(draft, bulkFolders),
  };
  const [onlyChild] = node.children;
  if (!isBulk && node.children.length === 1 && onlyChild && onlyChild.runCount === node.runCount) {
    return { ...onlyChild, label: `${node.label}/${onlyChild.label}` };
  }
  return node;
}

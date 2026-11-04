import { describe, expect, it } from "vitest";

import { ancestorFolders, buildFolderTree, findFolder, isFolderExpanded, relativeToFolder } from "./folderTree";

/** 트리는 경로·그룹만 본다. 그룹은 측정 서버가 대량 시도 폴더(`probes`)까지의 경로로 준다. */
function run(path: string, group: string | null = null) {
  return { path, group };
}

describe("buildFolderTree", () => {
  it("뿌리는 전체이고 폴더마다 그 아래 런 수를 센다", () => {
    const tree = buildFolderTree([
      run("guide/r1/a/chat.jsonl"),
      run("guide/r1/b/chat.jsonl"),
      run("guide/r2/a/chat.jsonl"),
      run("guide/r2/b/chat.jsonl"),
      run("solo.jsonl"),
    ]);

    expect(tree.path).toBe("");
    expect(tree.runCount).toBe(5);
    expect(tree.children.map((node) => [node.path, node.runCount])).toEqual([["guide", 4]]);
    expect(tree.children[0]?.children.map((node) => [node.label, node.runCount])).toEqual([
      ["r1", 2],
      ["r2", 2],
    ]);
  });

  it("런이 하나뿐인 폴더는 트리에 따로 두지 않는다 — 부모 폴더의 표에서 한 행이다", () => {
    const tree = buildFolderTree([run("tuning/R1/turns.jsonl"), run("tuning/R2/turns.jsonl")]);

    expect(tree.children.map((node) => node.path)).toEqual(["tuning"]);
    expect(tree.children[0]?.children).toEqual([]);
  });

  it("런 없이 폴더 하나만 품은 폴더는 한 줄로 합친다", () => {
    const tree = buildFolderTree([
      run("lm4/s3/probes/p1/a/chat.jsonl", "lm4/s3/probes"),
      run("lm4/s3/probes/p1/b/chat.jsonl", "lm4/s3/probes"),
    ]);

    expect(tree.children.map((node) => [node.label, node.path])).toEqual([["lm4/s3/probes", "lm4/s3/probes"]]);
  });

  it("대량 시도 폴더는 그 이름으로 남고 표시가 붙으며, 그 아래 폴더도 대량 시도 안으로 표시된다", () => {
    const tree = buildFolderTree([
      run("lm4/s3/probes/p1/a/chat.jsonl", "lm4/s3/probes"),
      run("lm4/s3/probes/p1/b/chat.jsonl", "lm4/s3/probes"),
      run("lm4/s3/probes/p2/a/chat.jsonl", "lm4/s3/probes"),
      run("lm4/smoke/a/chat.jsonl"),
      run("lm4/smoke/b/chat.jsonl"),
    ]);

    const probes = findFolder(tree, "lm4/s3/probes");
    expect(probes).toMatchObject({ label: "s3/probes", isBulk: true, isInBulk: true, runCount: 3 });
    expect(probes?.children.map((node) => [node.label, node.isBulk, node.isInBulk])).toEqual([["p1", false, true]]);
    expect(findFolder(tree, "lm4/smoke")).toMatchObject({ isBulk: false, isInBulk: false });
  });

  it("자식 폴더는 이름 순이다", () => {
    const tree = buildFolderTree([
      run("b/x/chat.jsonl"),
      run("b/y/chat.jsonl"),
      run("a/x/chat.jsonl"),
      run("a/y/chat.jsonl"),
    ]);

    expect(tree.children.map((node) => node.label)).toEqual(["a", "b"]);
  });

  it("런 하나짜리 폴더라도 그 아래 대량 시도 폴더를 품으면 남긴다", () => {
    const tree = buildFolderTree([run("solo/probes/p1/chat.jsonl", "solo/probes"), run("other/a/chat.jsonl")]);

    expect(findFolder(tree, "solo/probes")).toMatchObject({ label: "solo/probes", isBulk: true, runCount: 1 });
  });

  it("이름 앞부분만 같은 옆 폴더가 대량 시도 폴더를 품어도, 런 하나짜리 폴더는 그 때문에 남지 않는다", () => {
    const tree = buildFolderTree([run("run/x/chat.jsonl"), run("run2/probes/p1/chat.jsonl", "run2/probes")]);

    expect(tree.children.map((node) => node.path)).toEqual(["run2/probes"]);
    expect(findFolder(tree, "run")).toBeUndefined();
  });

  it("런이 없으면 뿌리만 남는다", () => {
    expect(buildFolderTree([])).toMatchObject({ path: "", runCount: 0, children: [] });
  });
});

describe("isFolderExpanded", () => {
  const tree = buildFolderTree([
    run("lm4/s3/probes/p1/a/chat.jsonl", "lm4/s3/probes"),
    run("lm4/s3/probes/p1/b/chat.jsonl", "lm4/s3/probes"),
    run("lm4/smoke/a/chat.jsonl"),
    run("lm4/smoke/b/chat.jsonl"),
  ]);
  const NO_OVERRIDES = new Map<string, boolean>();

  function folder(path: string) {
    const node = findFolder(tree, path);
    if (!node) throw new Error(`트리에 ${path} 가 없다`);
    return node;
  }

  it("손으로 바꾸지 않았으면 대량 시도 폴더와 그 아래는 접히고 나머지는 펼쳐진다", () => {
    expect(isFolderExpanded(folder("lm4/s3/probes"), NO_OVERRIDES)).toBe(false);
    expect(isFolderExpanded(folder("lm4/s3/probes/p1"), NO_OVERRIDES)).toBe(false);
    expect(isFolderExpanded(folder("lm4/smoke"), NO_OVERRIDES)).toBe(true);
    expect(isFolderExpanded(tree, NO_OVERRIDES)).toBe(true);
  });

  it("손으로 펼치거나 접은 값이 기본값을 이긴다", () => {
    const overrides = new Map([
      ["lm4/s3/probes", true],
      ["lm4/smoke", false],
    ]);

    expect(isFolderExpanded(folder("lm4/s3/probes"), overrides)).toBe(true);
    expect(isFolderExpanded(folder("lm4/smoke"), overrides)).toBe(false);
  });
});

describe("relativeToFolder", () => {
  it("고른 폴더를 앞에서 뗀다", () => {
    expect(relativeToFolder("guide/r1/a/chat.jsonl", "guide/r1")).toBe("a/chat.jsonl");
  });

  it("뿌리에서는 경로 그대로", () => {
    expect(relativeToFolder("guide/r1/a/chat.jsonl", "")).toBe("guide/r1/a/chat.jsonl");
  });
});

describe("ancestorFolders", () => {
  it("뿌리 다음부터 자기 자신 앞까지의 폴더", () => {
    expect(ancestorFolders("a/b/c")).toEqual(["a", "a/b"]);
    expect(ancestorFolders("a")).toEqual([]);
    expect(ancestorFolders("")).toEqual([]);
  });
});

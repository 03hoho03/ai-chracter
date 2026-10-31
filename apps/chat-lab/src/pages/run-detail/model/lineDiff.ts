export type DiffLine = {
  kind: "same" | "removed" | "added";
  text: string;
};

export type FoldedDiff = DiffLine | { kind: "folded"; count: number };

/**
 * 두 원문의 줄 단위 차이(최장 공통 부분열). 앞 원문에만 있는 줄은 `removed`, 뒤 원문에만 있는 줄은 `added` 이고 한 자리에서 둘이
 * 함께 바뀌면 빠진 줄을 먼저 둔다. 같은 앞머리·꼬리는 표를 만들기 전에 떼어 낸다 — 비교하는 두 프롬프트는 대개 거의 같아서
 * 표가 바뀐 구간만큼만 커진다.
 */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1;

  const midA = a.slice(head, a.length - tail);
  const midB = b.slice(head, b.length - tail);
  const same = (text: string): DiffLine => ({ kind: "same", text });
  return [...a.slice(0, head).map(same), ...diffMiddle(midA, midB), ...a.slice(a.length - tail).map(same)];
}

/** 바뀐 줄 앞뒤 `context` 줄만 남기고 나머지 같은 줄 구간을 접는다. */
export function foldDiff(lines: ReadonlyArray<DiffLine>, context: number): FoldedDiff[] {
  const changed = lines.map((line) => line.kind !== "same");
  const keep = lines.map((_, index) => {
    for (let offset = -context; offset <= context; offset += 1) {
      if (changed[index + offset]) return true;
    }
    return false;
  });

  const folded: FoldedDiff[] = [];
  lines.forEach((line, index) => {
    if (keep[index]) {
      folded.push(line);
      return;
    }
    const last = folded.at(-1);
    if (last?.kind === "folded") {
      last.count += 1;
    } else {
      folded.push({ kind: "folded", count: 1 });
    }
  });
  return folded;
}

function diffMiddle(a: ReadonlyArray<string>, b: ReadonlyArray<string>): DiffLine[] {
  const width = b.length + 1;
  // lcs[i * width + j] = a[i:] 와 b[j:] 의 최장 공통 부분열 길이.
  const lcs = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i * width + j] =
        a[i] === b[j]
          ? (lcs[(i + 1) * width + j + 1] ?? 0) + 1
          : Math.max(lcs[(i + 1) * width + j] ?? 0, lcs[i * width + j + 1] ?? 0);
    }
  }

  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    const lineA = a[i];
    const lineB = b[j];
    if (lineA !== undefined && lineA === lineB) {
      lines.push({ kind: "same", text: lineA });
      i += 1;
      j += 1;
    } else if (lineA !== undefined && (lineB === undefined || (lcs[(i + 1) * width + j] ?? 0) >= (lcs[i * width + j + 1] ?? 0))) {
      lines.push({ kind: "removed", text: lineA });
      i += 1;
    } else if (lineB !== undefined) {
      lines.push({ kind: "added", text: lineB });
      j += 1;
    }
  }
  return lines;
}

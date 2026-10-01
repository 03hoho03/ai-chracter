/**
 * 미디어 북 이미지 태그를 읽고 바꾸는 순수 함수. 규칙은 서버(`apps/api/src/api/content/media_tags.py`)와 같다 —
 * 두 구현이 갈라지면 빌더 미리보기와 실채팅이 같은 글을 다르게 그린다(같은 입력 표로 양쪽을 시험한다).
 *
 * 태그는 두 형태다.
 * - 이름 형태 `{{img::인물/장면}}` — 작성자가 빌더 글에 쓰는 형태. 본문에 슬래시가 정확히 하나다.
 * - id 형태 `{{img::<칸 id>}}` — 화면으로 나가는 글의 형태. 화면은 이 형태만 그림으로 바꾼다.
 * 둘 다 아닌 `{{…}}`(슬래시가 없거나 둘, 닫히지 않은 태그, `{{user}}` 같은 다른 문법)는 글이다.
 *
 * 태그를 지운 자리: 태그가 지워져 공백만 남은 줄은 줄째 없앤다. 그 때문에 빈 줄이 겹치면 하나로 접고, 글의
 * 처음·끝에 닿으면 빈 줄도 함께 없앤다. 태그와 무관하게 원래 있던 빈 줄 연속은 그대로 둔다.
 */

/** 칸 하나의 그림. 크기를 모르는 자산이면 `width`·`height` 가 없다(서버는 null 로 보낸다). */
export type MediaTagImage = { url: string; width?: number; height?: number };
/** `{칸 id: 그림}` 맵. 키는 소문자 정규형 칸 id 다. */
export type MediaTagImages = Record<string, MediaTagImage>;

const MEDIA_TAG = /\{\{img::([^{}\n]*)\}\}/g;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type ParsedTag = { kind: "id"; cellId: string } | { kind: "name"; person: string; scene: string };

/** 서버가 인물·장면 이름을 비교·저장하는 형태(앞뒤 공백 제거 + NFC). 빌더도 이 값으로 저장하고 길이·중복을 잰다. */
export function normalizeMediaBookName(name: string): string {
  return name.trim().normalize("NFC");
}

function parseTagBody(body: string): ParsedTag | undefined {
  const trimmed = body.trim();
  if (UUID.test(trimmed)) return { kind: "id", cellId: trimmed.toLowerCase() };
  const parts = body.split("/");
  if (parts.length !== 2) return undefined;
  const [person = "", scene = ""] = parts;
  return { kind: "name", person: normalizeMediaBookName(person), scene: normalizeMediaBookName(scene) };
}

export function toMediaIdTag(cellId: string): string {
  return `{{img::${cellId}}}`;
}

/** 칸을 가리키는 이름 형태 태그. 이름은 이미 정규화된(저장된) 값을 받는다. */
export function toMediaNameTag(personName: string, sceneName: string): string {
  return `{{img::${personName}/${sceneName}}}`;
}

/** 글에 이미지 태그(어느 형태든)가 들어 있는가 — 태그가 그림이 되지 않는 칸의 경고에 쓴다. */
export function hasMediaTag(text: string | undefined): boolean {
  return text !== undefined && text.includes("{{img::");
}

/** 태그마다 `replace` 를 불러 바꾼다(undefined 면 지운다). 지워서 비게 된 줄은 모듈 설명의 규칙으로 정리한다. */
function rewriteMediaTags(text: string, replace: (tag: ParsedTag, original: string) => string | undefined): string {
  if (!text.includes("{{img::")) return text;

  const lines = text.split("\n").map((line) => {
    let isDeleted = false;
    const rewritten = line.replace(MEDIA_TAG, (match, body: string) => {
      const parsed = parseTagBody(body);
      if (parsed === undefined) return match;
      const replacement = replace(parsed, match);
      if (replacement === undefined) {
        isDeleted = true;
        return "";
      }
      return replacement;
    });
    return { line: rewritten, isEmptied: isDeleted && rewritten.trim() === "" };
  });

  const result: string[] = [];
  let index = 0;
  while (index < lines.length) {
    const current = lines[index];
    if (current !== undefined && current.line.trim() !== "") {
      result.push(current.line);
      index += 1;
      continue;
    }
    let end = index;
    while (end < lines.length && lines[end]?.line.trim() === "") end += 1;
    const run = lines.slice(index, end);
    if (!run.some((item) => item.isEmptied)) {
      result.push(...run.map((item) => item.line));
    } else if (index !== 0 && end !== lines.length && run.some((item) => !item.isEmptied)) {
      result.push("");
    }
    index = end;
  }
  return result.join("\n");
}

/** 미디어 북 칸 하나 — 인물·장면 이름과 칸 id. */
export type MediaTagCell = { person: string; scene: string; cellId: string };

/**
 * 이름 형태 태그를 칸 id 형태로 바꾸고 글이 가리키는 칸 id 를 함께 돌려준다. 이름은 정규화해 비교하므로 표의
 * 이름이 정규화되지 않았어도 같은 칸을 찾는다. 없는 이름의 태그는 지운다(화면은 원문 대신 빈칸). id 형태 태그는
 * 그 칸이 표에 있으면 정규형으로 남기고 없으면 지운다.
 */
export function normalizeMediaTags(
  text: string,
  cells: readonly MediaTagCell[],
): { text: string; cellIds: Set<string> } {
  const byName = new Map(cells.map((cell) => [nameKey(cell.person, cell.scene), cell.cellId.toLowerCase()]));
  const knownIds = new Set(byName.values());
  const cellIds = new Set<string>();
  const normalized = rewriteMediaTags(text, (tag) => {
    const cellId = tag.kind === "id" ? tag.cellId : byName.get(nameKey(tag.person, tag.scene));
    if (cellId === undefined || !knownIds.has(cellId)) return undefined;
    cellIds.add(cellId);
    return toMediaIdTag(cellId);
  });
  return { text: normalized, cellIds };
}

// 인물·장면 이름에는 `/` 가 들어갈 수 없어 구분자로 안전하다.
function nameKey(person: string, scene: string): string {
  return `${normalizeMediaBookName(person)}/${normalizeMediaBookName(scene)}`;
}

/** 미디어 북의 두 축. 이름 형태 태그의 슬래시 앞이 인물, 뒤가 장면이다. */
export type MediaBookAxis = "person" | "scene";

/**
 * 인물이나 장면 이름이 바뀌었을 때 글 속 이름 형태 태그를 새 이름으로 바꾼다. 태그 안에서 그 축 자리의 이름이
 * 정확히 같을 때만 바꾼다 — 글자열 치환이 아니므로 `리아`를 바꿔도 `마리아`가 든 태그나 태그 밖 글은 그대로다.
 * id 형태와 태그가 아닌 `{{…}}` 는 손대지 않는다.
 */
export function renameMediaTagName(text: string, axis: MediaBookAxis, oldName: string, newName: string): string {
  const from = normalizeMediaBookName(oldName);
  const to = normalizeMediaBookName(newName);
  return rewriteMediaTags(text, (tag, original) => {
    if (tag.kind !== "name" || tag[axis] !== from) return original;
    return axis === "person" ? toMediaNameTag(to, tag.scene) : toMediaNameTag(tag.person, to);
  });
}

/** 글 속 이름 형태 태그를 나온 순서대로(중복 포함) — 원문과 정규화한 인물·장면 이름. id 형태·태그가 아닌 `{{…}}` 는 뺀다. */
export function findMediaNameTags(text: string): { original: string; person: string; scene: string }[] {
  if (!text.includes("{{img::")) return [];
  return [...text.matchAll(MEDIA_TAG)].flatMap((match) => {
    const parsed = parseTagBody(match[1] ?? "");
    return parsed?.kind === "name" ? [{ original: match[0], person: parsed.person, scene: parsed.scene }] : [];
  });
}

/** 두 형태의 태그를 모두 지운다 — 그림을 그리지 않는 자리(접힌 미리보기·봇 메타)에 쓴다. */
export function stripMediaTags(text: string): string {
  return rewriteMediaTags(text, () => undefined);
}

/**
 * 맵에 없는 칸을 가리키는 id 형태 태그를 지운다(지워진 칸·다른 버전의 칸 — 화면은 빈칸). 이름 형태와 그 밖의
 * `{{…}}` 는 그대로 둔다 — 화면은 id 형태만 그림으로 바꾸고, 나머지는 글이다.
 */
export function dropUnresolvedMediaTags(text: string, images: MediaTagImages): string {
  return rewriteMediaTags(text, (tag, original) => {
    if (tag.kind === "name") return original;
    return tag.cellId in images ? toMediaIdTag(tag.cellId) : undefined;
  });
}

/** 글 속 칸 id 형태 태그의 자리와 칸 id(소문자 정규형)를 나온 순서대로. 이름 형태·태그가 아닌 `{{…}}` 는 빼고 센다. */
export function findMediaIdTags(text: string): { index: number; length: number; cellId: string }[] {
  if (!text.includes("{{img::")) return [];
  return [...text.matchAll(MEDIA_TAG)].flatMap((match) => {
    const cellId = parseMediaIdTagBody(match[1] ?? "");
    return cellId === undefined ? [] : [{ index: match.index, length: match[0].length, cellId }];
  });
}

/** 글 속 id 형태 태그 하나의 칸 id(소문자 정규형). 이름 형태나 태그가 아닌 본문이면 undefined. */
function parseMediaIdTagBody(body: string): string | undefined {
  const parsed = parseTagBody(body);
  return parsed?.kind === "id" ? parsed.cellId : undefined;
}

export type MediaTagTextSegment = { kind: "text"; text: string } | { kind: "image"; cellId: string };

/**
 * 평문을 글 조각과 그림 자리로 나눈다(맵에 있는 칸의 id 형태 태그만 그림). 그림 바로 앞뒤의 줄바꿈은 조각에서
 * 걷어 낸다 — 그림은 제 줄을 차지하는 블록이라 태그를 감싼 빈 줄이 블록 사이 간격과 겹친다. 빈 조각은 버린다.
 */
export function splitMediaTagText(text: string, images: MediaTagImages): MediaTagTextSegment[] {
  const source = dropUnresolvedMediaTags(text, images);
  const segments: MediaTagTextSegment[] = [];
  let cursor = 0;
  for (const tag of findMediaIdTags(source)) {
    if (!(tag.cellId in images)) continue;
    segments.push({ kind: "text", text: source.slice(cursor, tag.index) });
    segments.push({ kind: "image", cellId: tag.cellId });
    cursor = tag.index + tag.length;
  }
  segments.push({ kind: "text", text: source.slice(cursor) });

  return segments.flatMap((segment, index): MediaTagTextSegment[] => {
    if (segment.kind === "image") return [segment];
    let value = segment.text;
    if (segments[index - 1]?.kind === "image") value = value.replace(/^[ \t]*\n+/, "");
    if (segments[index + 1]?.kind === "image") value = value.replace(/\n+[ \t]*$/, "");
    return value.trim() === "" ? [] : [{ kind: "text", text: value }];
  });
}

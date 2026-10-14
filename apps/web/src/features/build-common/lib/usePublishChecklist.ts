import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FieldValues, Path, UseFormReturn } from "react-hook-form";
import type { z } from "zod";

import type { BuilderTab } from "@/entities/content";

import {
  completedTabIds as toCompletedTabIds,
  unchangedServerIssues,
  valueSnapshot,
  type ServerIssue,
} from "../model/publishIssues";

/** 값이 바뀐 뒤 발행 검사를 다시 돌리기까지 기다리는 시간. 입력하는 동안은 돌지 않고 멈추면 한 번 돈다 — 긴 초안에서 검사 한 번이
 * 1ms 남짓이라 이보다 길게 미루면 고친 줄이 늦게 빠져 보이고, 키마다 돌리면 입력 중 메인 스레드를 쓴다. */
const EVALUATE_DELAY_MS = 300;

export type ServerIssueInput = { path: string; message: string; label?: string };

type ClientIssue = { path: string; message: string };

function schemaIssues(schema: z.ZodType, values: unknown): ClientIssue[] {
  const result = schema.safeParse(values);
  if (result.success) return [];
  return result.error.issues.map((issue) => ({ path: issue.path.map(String).join("."), message: issue.message }));
}

function samePaths(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((path, index) => path === b[index]);
}

/**
 * 발행 검사를 지금 값에 대해 계속 돌려 두 가지를 맞춘다.
 *
 * - **채움 표시** — 필수 탭마다 발행 검사 오류도, 남은 서버 거절도 없는지(`completedTabIds`). 발행을 누르기 전에도 돈다.
 * - **오류 갈아 끼우기** — 발행을 한 번 누른 뒤부터 값이 바뀌면 클라 오류를 검사 결과로 통째로 바꾼다. RHF 는 입력한 칸 이름의
 *   오류만 다시 따지므로, 오류가 다른 칸에 걸리는 교차 검사(최소값을 고쳤는데 오류는 최대값 칸)나 `setValue` 로 쓰는 칸(키워드 칩)을
 *   고쳐도 오류가 남았다. 서버 거절(`type: "server"`)은 클라 검사로 다시 따질 수 없어 남기되, 그 자리 값이 바뀌면 지운다
 *   (`unchangedServerIssues`).
 *
 * 둘 다 `form.watch` 구독에 디바운스를 걸어 입력이 멈출 때 한 번만 검사한다(자동저장 구독과 같은 모양이라 셸을 다시 그리지 않는다).
 * 오류 교체는 `trigger()` 로 한다 — 리졸버가 필드 배열 자리 오류를 `.root` 에 담는 규칙을 그대로 따르려는 것이다. 바로 뒤에 남은
 * 서버 거절을 다시 건다. 검사 결과가 직전에 건 것과 같으면 건너뛴다(오류가 그대로인데 셸을 다시 그리지 않게).
 */
export function usePublishChecklist<T extends FieldValues>({
  form,
  schema,
  tabs,
  requiredTabIds,
}: {
  form: UseFormReturn<T>;
  schema: z.ZodType;
  tabs: readonly BuilderTab[];
  requiredTabIds: ReadonlySet<string>;
}) {
  const hasAttemptedRef = useRef(false);
  const serverIssuesRef = useRef<ServerIssue[]>([]);
  const appliedSignatureRef = useRef<string | undefined>(undefined);
  const [clientPaths, setClientPaths] = useState(() =>
    schemaIssues(schema, form.getValues()).map((issue) => issue.path),
  );
  const [serverPaths, setServerPaths] = useState<string[]>([]);

  const applyServerIssues = useCallback(
    (issues: readonly ServerIssue[]) => {
      for (const issue of issues) {
        // 경로는 서버 키나 오류 객체에서 런타임에 얻은 문자열이라 Path<T> 로 정적으로 좁힐 수 없다.
        // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
        form.setError(issue.path as Path<T>, { type: "server", message: issue.message });
      }
    },
    [form],
  );

  const keepServerIssues = useCallback((issues: ServerIssue[]) => {
    serverIssuesRef.current = issues;
    const paths = issues.map((issue) => issue.path);
    setServerPaths((previous) => (samePaths(previous, paths) ? previous : paths));
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;

    function evaluate() {
      const values = form.getValues();
      const clientIssues = schemaIssues(schema, values);
      const nextClientPaths = clientIssues.map((issue) => issue.path);
      setClientPaths((previous) => (samePaths(previous, nextClientPaths) ? previous : nextClientPaths));
      const kept = unchangedServerIssues(serverIssuesRef.current, values);
      keepServerIssues(kept);

      if (!hasAttemptedRef.current) return;
      const signature = JSON.stringify([clientIssues, kept.map((issue) => issue.path)]);
      if (signature === appliedSignatureRef.current) return;
      appliedSignatureRef.current = signature;
      void form.trigger().then(() => applyServerIssues(kept));
    }

    const subscription = form.watch(() => {
      clearTimeout(timer);
      timer = setTimeout(evaluate, EVALUATE_DELAY_MS);
    });
    return () => {
      subscription.unsubscribe();
      clearTimeout(timer);
    };
  }, [form, schema, applyServerIssues, keepServerIssues]);

  /** 발행 버튼을 누를 때 부른다. 이때부터 값이 바뀌면 오류를 갈아 끼운다(누르기 전에는 오류를 띄우지 않는다). */
  const markAttempted = useCallback(() => {
    hasAttemptedRef.current = true;
    appliedSignatureRef.current = undefined;
  }, []);

  /** 서버 거절을 건다. 같은 자리를 가리키는 키가 여럿이면(키워드북 두 키) 이름을 이어 한 줄로 둔다. 빈 배열이면 남은 거절을 모두 지운다. */
  const setServerIssues = useCallback(
    (inputs: readonly ServerIssueInput[]) => {
      const values = form.getValues();
      const byPath = new Map<string, ServerIssue>();
      for (const input of inputs) {
        const existing = byPath.get(input.path);
        const label =
          existing?.label !== undefined && input.label !== undefined
            ? `${existing.label}, ${input.label}`
            : (input.label ?? existing?.label);
        byPath.set(input.path, { ...input, label, snapshot: valueSnapshot(values, input.path) });
      }
      const issues = [...byPath.values()];
      keepServerIssues(issues);
      appliedSignatureRef.current = undefined;
      applyServerIssues(issues);
    },
    [form, applyServerIssues, keepServerIssues],
  );

  /** 발행 검사가 오류 객체를 통째로 바꾼 직후(다시 누른 발행이 클라 검사에서 막힘) 아직 유효한 서버 거절을 다시 건다. 건 경로를 돌려준다. */
  const reapplyServerIssues = useCallback((): string[] => {
    const kept = unchangedServerIssues(serverIssuesRef.current, form.getValues());
    keepServerIssues(kept);
    applyServerIssues(kept);
    return kept.map((issue) => issue.path);
  }, [form, applyServerIssues, keepServerIssues]);

  /** 그 자리에 남은 서버 거절이 준 칸 이름. 없으면 `undefined` 라 호출부가 칸 라벨 표에서 찾는다. */
  const serverLabel = useCallback(
    (path: string) => serverIssuesRef.current.find((issue) => issue.path === path)?.label,
    [],
  );

  const completedTabIds = useMemo(
    () => toCompletedTabIds(requiredTabIds, [...clientPaths, ...serverPaths], tabs),
    [requiredTabIds, clientPaths, serverPaths, tabs],
  );

  return { completedTabIds, markAttempted, setServerIssues, reapplyServerIssues, serverLabel };
}

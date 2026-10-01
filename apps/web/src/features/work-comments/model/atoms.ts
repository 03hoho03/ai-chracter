import { atom } from "jotai";

import type { CommentDraftScope } from "./draftScope";

export const draftScopesAtom = atom<Record<string, CommentDraftScope>>({});

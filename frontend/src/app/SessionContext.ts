import { createContext } from "react";

import type { Session } from "../types/session";

export const SessionContext = createContext<Session | null>(null);

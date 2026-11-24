import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { SessionProvider } from "./app/SessionProvider";
import { ToastProvider } from "./app/ToastProvider";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

createRoot(root).render(
  <StrictMode>
    <ToastProvider>
      <SessionProvider>
        <App />
      </SessionProvider>
    </ToastProvider>
  </StrictMode>,
);

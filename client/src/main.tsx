import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./app/styles.css";
import { initializeColorTheme } from "./features/theme/colorTheme";

initializeColorTheme();

const root = document.getElementById("root");

if (root === null) {
  throw new Error("ResFinance root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

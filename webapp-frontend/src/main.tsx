import { init } from "@telegram-apps/sdk";
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";

init();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

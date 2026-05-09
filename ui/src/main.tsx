import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root missing in index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Disable browser context menu — we'll ship our own NSMenu-style menu later.
window.addEventListener("contextmenu", (e) => e.preventDefault());

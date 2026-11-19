import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import "./index.css";
import { AuthProvider } from "./auth/AuthContext";
import { TenantQueryBoundary } from "./auth/TenantQueryBoundary";
import { router } from "./routes/router";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      {/* A fresh query cache (and remount) for every user + organization context. */}
      <TenantQueryBoundary>
        <RouterProvider router={router} />
      </TenantQueryBoundary>
    </AuthProvider>
  </React.StrictMode>
);

import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { clearStoredAuth, fetchBrowserSession } from "../utils/auth";

const ProtectedRoute = ({ children }) => {
  const location = useLocation();
  const [sessionStatus, setSessionStatus] = useState("loading");

  useEffect(() => {
    let active = true;
    fetchBrowserSession()
      .then(() => {
        if (active) setSessionStatus("authenticated");
      })
      .catch(() => {
        clearStoredAuth();
        if (active) setSessionStatus("unauthenticated");
      });
    return () => {
      active = false;
    };
  }, []);

  if (sessionStatus === "loading") {
    return null;
  }

  if (sessionStatus === "unauthenticated") {
    return <Navigate to="/sign-in" replace state={{ from: location }} />;
  }

  return children;
};

export default ProtectedRoute;

import { Navigate, useLocation } from "react-router-dom";
import { clearStoredAuth, hasValidStoredSession } from "../utils/auth";

const ProtectedRoute = ({ children }) => {
  const location = useLocation();

  if (!hasValidStoredSession()) {
    clearStoredAuth();
    return <Navigate to="/sign-in" replace state={{ from: location }} />;
  }

  return children;
};

export default ProtectedRoute;

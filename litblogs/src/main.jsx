import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google'
import { MsalProvider } from "@azure/msal-react"
import { PublicClientApplication } from "@azure/msal-browser"
import { msalConfig } from './config/msalConfig'
import App from './App'
import './index.css'
import axios from 'axios'
import { API_BASE_PATH, APP_BASE_PATH, ROUTER_BASENAME } from './utils/urlUtils'
import {
  clearStoredAuth,
  configureAuthHttpClient,
  purgeLegacyPersistentAuth,
} from './utils/auth'

// Initialize MSAL instance
const msalInstance = new PublicClientApplication(msalConfig);

// Set base URL for all axios requests
axios.defaults.baseURL = API_BASE_PATH;
configureAuthHttpClient(axios, { apiBasePath: API_BASE_PATH });
purgeLegacyPersistentAuth();

axios.interceptors.response.use(
  (response) => response,
  (error) => {
    const isUnauthorized = error?.response?.status === 401;

    if (isUnauthorized) {
      clearStoredAuth();

      if (typeof window !== "undefined") {
        const signInPath = `${APP_BASE_PATH || ""}/sign-in`;
        if (window.location.pathname !== signInPath) {
          window.location.replace(signInPath);
        }
      }
    }

    return Promise.reject(error);
  }
);

// Optional - Handle the response from auth redirects
msalInstance.initialize().then(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <MsalProvider instance={msalInstance}>
        <GoogleOAuthProvider clientId="653922429771-qdjgvs7vkrcd7g4o2oea12t097ah4eog.apps.googleusercontent.com">
          <BrowserRouter basename={ROUTER_BASENAME}>
            <App />
          </BrowserRouter>
        </GoogleOAuthProvider>
      </MsalProvider>
    </React.StrictMode>
  )
});

import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google'
import { MsalProvider } from "@azure/msal-react"
import { PublicClientApplication } from "@azure/msal-browser"
import {
  applyPublicOAuthConfig,
  msalConfig,
  oauthProviderConfig,
} from './config/msalConfig'
import { loadPublicRuntimeConfig } from './config/runtimeConfig'
import App from './App'
import './index.css'
import axios from 'axios'
import { API_BASE_PATH, APP_BASE_PATH, ROUTER_BASENAME } from './utils/urlUtils'
import {
  clearStoredAuth,
  configureAuthHttpClient,
  purgeLegacyPersistentAuth,
} from './utils/auth'

// Set base URL for all axios requests
axios.defaults.baseURL = API_BASE_PATH;
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

const renderApplication = (msalInstance) => {
  let application = (
    <BrowserRouter basename={ROUTER_BASENAME}>
      <App />
    </BrowserRouter>
  );

  if (oauthProviderConfig.google.enabled) {
    application = (
      <GoogleOAuthProvider clientId={oauthProviderConfig.google.clientId}>
        {application}
      </GoogleOAuthProvider>
    );
  }

  if (msalInstance) {
    application = <MsalProvider instance={msalInstance}>{application}</MsalProvider>;
  }

  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      {application}
    </React.StrictMode>
  );
};

const renderConfigurationFailure = () => {
  const root = document.getElementById('root');
  root.textContent = 'LitBlogs is temporarily unavailable. Please contact your school administrator.';
};

const initializeApplication = async () => {
  const runtimeConfig = await loadPublicRuntimeConfig();
  applyPublicOAuthConfig(runtimeConfig);
  configureAuthHttpClient(axios, {
    apiBasePath: API_BASE_PATH,
    csrfCookieName: runtimeConfig.csrfCookieName,
  });

  const msalInstance = oauthProviderConfig.microsoft.enabled
    ? new PublicClientApplication(msalConfig)
    : null;
  if (msalInstance) {
    await msalInstance.initialize();
  }
  renderApplication(msalInstance);
};

initializeApplication().catch(renderConfigurationFailure);

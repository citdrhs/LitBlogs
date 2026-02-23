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

// Initialize MSAL instance
const msalInstance = new PublicClientApplication(msalConfig);

// Set base URL for all axios requests
axios.defaults.baseURL = 'https://drhscit.org/dren';

// Optional - Handle the response from auth redirects
msalInstance.initialize().then(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <MsalProvider instance={msalInstance}>
        <GoogleOAuthProvider clientId="653922429771-qdjgvs7vkrcd7g4o2oea12t097ah4eog.apps.googleusercontent.com">
          <BrowserRouter basename="/dren">
            <App />
          </BrowserRouter>
        </GoogleOAuthProvider>
      </MsalProvider>
    </React.StrictMode>
  )
});

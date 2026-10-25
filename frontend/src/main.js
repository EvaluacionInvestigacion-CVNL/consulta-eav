import { createApp } from 'vue'
import * as Sentry from '@sentry/vue'
import App from './App.vue'
import './input.css'

const app = createApp(App)

Sentry.init({
  app,
  dsn: import.meta.env.VITE_SENTRY_DSN,
  environment: import.meta.env.MODE,
  release: __SENTRY_RELEASE__ || undefined,
  integrations: [Sentry.browserTracingIntegration()],
  tracesSampleRate: 0.1,
  sendDefaultPii: false,
})

app.mount('#app')

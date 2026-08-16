import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Self-hosted through @fontsource: the design system's stylesheet imports these
// from Google Fonts, which would add a third-party request to a product whose
// external calls are enumerated and auditable (01 section 8).
import '@fontsource/barlow/400.css'
import '@fontsource/barlow/500.css'
import '@fontsource/barlow/700.css'
import '@fontsource/barlow-condensed/400.css'
import '@fontsource/barlow-condensed/600.css'
import 'mapbox-gl/dist/mapbox-gl.css'

import App from './App'
import './styles.css'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // Local single-user data changes only when this UI changes it, so
      // background refetching would be pure noise.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)

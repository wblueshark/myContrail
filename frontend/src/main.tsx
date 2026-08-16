import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

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

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import { TooltipProvider } from './components/ui/tooltip.tsx';
import { AuthProvider } from './contexts/AuthContext.tsx';
import { store } from './store/index.ts';

import './tailwind.css';
import './styles/theme.scss';

import App from './App.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Provider store={store}>
      <AuthProvider>
        <TooltipProvider disableHoverableContent>
          <App />
        </TooltipProvider>
      </AuthProvider>
    </Provider>
  </StrictMode>
);

import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { Layout } from '@/components';
import ProtectedRoute from '@/components/auth/ProtectedRoute';
import { Anomalies, Chat, Dashboard, Graph, SignIn, Users } from '@/pages';

function RootElement() {
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<SignIn />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<RootElement />}>
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="anomalies" element={<Anomalies />} />
            <Route path="chat" element={<Chat />} />
            <Route path="chat/:conversationId" element={<Chat />} />
            <Route path="users" element={<Users />} />
            <Route path="graph" element={<Graph />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;

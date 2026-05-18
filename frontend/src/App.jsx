import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import Chat from './pages/Chat';
import Metrics from './pages/Metrics';

function App() {
  const [merchantId, setMerchantId] = useState(() => {
    return localStorage.getItem('merchantId') || '';
  });

  useEffect(() => {
    localStorage.setItem('merchantId', merchantId);
  }, [merchantId]);

  return (
    <BrowserRouter>
      <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <Navbar merchantId={merchantId} setMerchantId={setMerchantId} />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<Chat merchantId={merchantId} />} />
            <Route path="/metrics" element={<Metrics merchantId={merchantId} />} />
          </Routes>
        </div>
        <Footer />
      </div>
    </BrowserRouter>
  );
}

export default App;

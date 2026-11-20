/**
 * Dental Agent — AI-Powered Dental Clinic Management
 * سامانه مدیریت کلینیک دندانپزشکی با دستیار هوش مصنوعی عاملمحور
 */

import React from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ClinicProvider } from './context/ClinicContext';
import { AppLayout } from './components/layout/AppLayout';
import { LoginView } from './components/auth/LoginView';
import { ConnectionLostView } from './components/common/ConnectionLostView';

const AppContent: React.FC = () => {
  const { isAuthenticated, isLoading, connectionLost, refreshUser } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas text-caption text-muted" dir="rtl">
        در حال بررسی نشست شما...
      </div>
    );
  }

  if (!isAuthenticated && connectionLost) {
    return <ConnectionLostView onRetry={refreshUser} />;
  }

  if (!isAuthenticated) {
    return <LoginView />;
  }

  return <AppLayout />;
};

export default function App() {
  return (
    <AuthProvider>
      <ClinicProvider>
        <AppContent />
      </ClinicProvider>
    </AuthProvider>
  );
}

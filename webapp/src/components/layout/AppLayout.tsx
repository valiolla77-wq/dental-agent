import React, { useEffect, useState } from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { ConnectionBanner } from '../common/ConnectionBanner';
import { AgentDrawer } from '../agent/AgentDrawer';
import { DashboardView } from '../dashboard/DashboardView';
import { AppointmentsView } from '../appointments/AppointmentsView';
import { PatientsView } from '../patients/PatientsView';
import { TeamView } from '../team/TeamView';
import { AgentView } from '../agent/AgentView';
import { ReportsView } from '../reports/ReportsView';
import { StaffView } from '../staff/StaffView';
import { DoctorsManageView } from '../doctors/DoctorsManageView';
import { ProfileView } from '../profile/ProfileView';
import { DoctorPatientsView } from '../patients/DoctorPatientsView';
import { HealthRecordView } from '../health/HealthRecordView';
import { ReceptionView } from '../reception/ReceptionView';
import { SystemHealthView } from '../system/SystemHealthView';
import { useAuth } from '../../context/AuthContext';
import { UserRole } from '../../types';

const ROLE_VIEWS: Record<UserRole, string[]> = {
  admin: ['dashboard', 'reception', 'agent', 'appointments', 'patients', 'doctors', 'reports', 'staff', 'system-health', 'profile'],
  receptionist: ['dashboard', 'reception', 'agent', 'appointments', 'patients', 'profile'],
  doctor: ['dashboard', 'reception', 'agent', 'patients', 'profile'],
  patient: ['dashboard', 'team', 'appointments', 'health', 'agent', 'profile'],
};

export const AppLayout: React.FC = () => {
  const [currentView, setCurrentView] = useState('dashboard');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { currentUser } = useAuth();
  const role = currentUser?.role || 'patient';

  // A role change (or a fresh login) must never leave the user on a view
  // their role cannot access.
  useEffect(() => {
    if (!ROLE_VIEWS[role].includes(currentView)) {
      setCurrentView('dashboard');
    }
  }, [role, currentView]);

  const renderActiveView = () => {
    switch (currentView) {
      case 'dashboard':
        return <DashboardView onNavigate={setCurrentView} />;
      case 'reception':
        return role === 'patient' ? null : <ReceptionView />;
      case 'agent':
        return <AgentView />;
      case 'appointments':
        return <AppointmentsView />;
      case 'health':
        return role === 'patient' ? <HealthRecordView /> : null;
      case 'patients':
        return role === 'doctor' ? <DoctorPatientsView /> : <PatientsView />;
      // Patient-facing booking catalog keeps its read-only view; the admin
      // gets the full management surface (CRUD + schedules + account links).
      case 'team':
        return <TeamView onNavigate={setCurrentView} />;
      case 'doctors':
        return role === 'admin' ? <DoctorsManageView /> : null;
      case 'reports':
        return role === 'admin' ? <ReportsView onNavigate={setCurrentView} /> : null;
      case 'staff':
        return role === 'admin' ? <StaffView /> : null;
      case 'system-health':
        return role === 'admin' ? <SystemHealthView /> : null;
      case 'profile':
        return <ProfileView onNavigate={setCurrentView} />;
      default:
        return <DashboardView onNavigate={setCurrentView} />;
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col" dir="rtl">
      <Header
        currentView={currentView}
        onSelectView={setCurrentView}
        onOpenMobileMenu={() => setMobileMenuOpen(true)}
      />
      <ConnectionBanner />
      <main className="flex-1 min-w-0">{renderActiveView()}</main>

      <Sidebar
        currentView={currentView}
        onSelectView={setCurrentView}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      <AgentDrawer />
    </div>
  );
};

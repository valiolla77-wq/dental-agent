import React, { useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../common/Button';
import { PageHeader } from '../common/ui';
import { AppointmentBookingModal } from '../appointments/AppointmentBookingModal';
import { NewPatientModal } from '../patients/NewPatientModal';
import { AdminDashboardPanel } from './AdminDashboardPanel';
import { ReceptionistDashboardPanel } from './ReceptionistDashboardPanel';
import { DoctorDashboardPanel } from './DoctorDashboardPanel';
import { PatientDashboardPanel } from './PatientDashboardPanel';
import { CalendarPlus, FileBarChart2, UserPlus } from 'lucide-react';

interface DashboardViewProps {
  onNavigate: (view: string) => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({ onNavigate }) => {
  const { currentUser, hasPerm } = useAuth();
  const { setAgentDrawerOpen } = useClinic();
  const [bookingOpen, setBookingOpen] = useState(false);
  const [newPatientOpen, setNewPatientOpen] = useState(false);

  const role = currentUser?.role || 'patient';
  const firstName = (currentUser?.full_name || '').trim().split(' ')[0];

  const titles: Record<string, string> = {
    admin: 'هر لبخند، یک شروع خوب',
    receptionist: 'امروز، میز پذیرش آماده است',
    doctor: `${currentUser?.full_name || 'دکتر'}، روز خوبی داشته باشید`,
    patient: `${firstName || 'دوست'} جان، به خانه لبخندت خوش آمدی`,
  };

  const subtitles: Record<string, string> = {
    admin: 'خلاصه‌ای از نبض امروز کلینیک؛ همه اعداد از داده‌های ثبت‌شده در سرور محاسبه می‌شوند.',
    receptionist: 'نوبت‌های امروز، پرونده‌های نیازمند تکمیل و مسیر سریع پذیرش در یک نگاه.',
    doctor: 'برنامه امروز، نوبت‌های پیش‌رو و دسترسی سریع به بیماران مجاز.',
    patient: 'نوبت بعدی، مسیر درمان و دستیار شخصی شما در یک نگاه.',
  };

  const canBook =
    hasPerm('book_appointment') && (role !== 'patient' || Boolean(currentUser?.patient));

  const action = (
    <>
      {role === 'admin' && (
        <Button
          variant="outline"
          size="md"
          onClick={() => onNavigate('reports')}
          icon={<FileBarChart2 className="w-4 h-4" />}
        >
          گزارش کامل
        </Button>
      )}
      {role === 'receptionist' && hasPerm('manage_patients') && (
        <Button
          variant="outline"
          size="md"
          onClick={() => setNewPatientOpen(true)}
          icon={<UserPlus className="w-4 h-4" />}
        >
          ثبت بیمار
        </Button>
      )}
      {canBook && (
        <Button
          size="md"
          onClick={() => setBookingOpen(true)}
          icon={<CalendarPlus className="w-4 h-4" />}
        >
          رزرو نوبت جدید
        </Button>
      )}
    </>
  );

  return (
    <div className="d-page d-fade">
      <PageHeader
        title={titles[role]}
        subtitle={subtitles[role]}
        eyebrow={role === 'admin' ? 'گزارش روز کلینیک' : undefined}
        action={action}
      />

      {role === 'admin' && (
        <AdminDashboardPanel
          onNavigate={onNavigate}
          onBook={() => setBookingOpen(true)}
          onOpenAgent={() => setAgentDrawerOpen(true)}
        />
      )}
      {role === 'receptionist' && (
        <ReceptionistDashboardPanel
          onNavigate={onNavigate}
          onBook={() => setBookingOpen(true)}
          onNewPatient={() => setNewPatientOpen(true)}
        />
      )}
      {role === 'doctor' && <DoctorDashboardPanel onNavigate={onNavigate} />}
      {role === 'patient' && (
        <PatientDashboardPanel
          onNavigate={onNavigate}
          onBook={() => setBookingOpen(true)}
        />
      )}

      <AppointmentBookingModal isOpen={bookingOpen} onClose={() => setBookingOpen(false)} />
      <NewPatientModal isOpen={newPatientOpen} onClose={() => setNewPatientOpen(false)} />
    </div>
  );
};

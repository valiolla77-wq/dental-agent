import React, { useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../common/Button';
import { AppointmentBookingModal } from '../appointments/AppointmentBookingModal';
import { Stethoscope, Plus, Phone, CheckCircle2, XCircle } from 'lucide-react';

export const DoctorsView: React.FC = () => {
  const { doctors } = useClinic();
  const { hasPerm } = useAuth();
  const [bookingModalOpen, setBookingModalOpen] = useState(false);

  return (
    <div className="space-y-5 p-4 md:p-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-ink tracking-tight">کادر دندانپزشکان متخصص</h2>
          <p className="text-caption text-muted">
            فهرست پزشکان کلینیک، تخصص‌ها و وضعیت فعالیت (متصل به GET /doctors/)
          </p>
        </div>

        {hasPerm('book_appointment') && (
          <Button
            variant="teal"
            size="sm"
            onClick={() => setBookingModalOpen(true)}
            icon={<Plus className="w-4 h-4" />}
          >
            رزرو وقت با پزشک
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {doctors.map((doctor) => (
          <div
            key={doctor.id}
            className="bg-surface rounded-xl border border-line shadow-2xs overflow-hidden flex flex-col justify-between"
          >
            <div className="p-5 space-y-4">
              <div className="flex items-start gap-3.5">
                <div className="w-12 h-12 rounded-xl bg-primary-soft border border-primary-line/80 flex items-center justify-center text-primary-deep shrink-0">
                  <Stethoscope className="w-6 h-6" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <h3 className="font-bold text-ink text-sm truncate">{doctor.full_name}</h3>
                    {doctor.is_active ? (
                      <span className="text-caption bg-success-soft text-success border border-success-line px-1.5 py-0.5 rounded flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>فعال</span>
                      </span>
                    ) : (
                      <span className="text-caption bg-surface-muted text-muted px-1.5 py-0.5 rounded flex items-center gap-1">
                        <XCircle className="w-3 h-3" />
                        <span>غیرفعال</span>
                      </span>
                    )}
                  </div>
                  <p className="text-caption text-primary-deep font-medium mt-1 leading-snug">
                    {doctor.specialty}
                  </p>
                  <div className="text-small text-faint mt-1 font-mono-numbers">
                    شناسه پزشک: #{doctor.id}
                  </div>
                </div>
              </div>

              {doctor.phone && (
                <div className="space-y-2 text-caption pt-3 border-t border-line text-muted">
                  <div className="flex items-center gap-2">
                    <Phone className="w-3.5 h-3.5 text-faint shrink-0" />
                    <span>شماره تماس: </span>
                    <span className="font-mono-numbers text-ink">{doctor.phone}</span>
                  </div>
                </div>
              )}
            </div>

            <div className="p-4 bg-canvas border-t border-line flex items-center justify-between">
              <span className="text-small text-muted">
                سیستم نوبت‌دهی آنلاین فعال
              </span>

              {hasPerm('book_appointment') && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setBookingModalOpen(true)}
                >
                  رزرو نوبت
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>

      <AppointmentBookingModal
        isOpen={bookingModalOpen}
        onClose={() => setBookingModalOpen(false)}
      />
    </div>
  );
};

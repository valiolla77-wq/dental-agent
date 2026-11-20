import React, { useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../common/Button';
import { AppointmentBookingModal } from '../appointments/AppointmentBookingModal';
import { Sparkles, Plus, CheckCircle2, XCircle } from 'lucide-react';

export const ServicesView: React.FC = () => {
  const { services } = useClinic();
  const { hasPerm } = useAuth();
  const [bookingModalOpen, setBookingModalOpen] = useState(false);

  return (
    <div className="space-y-5 p-4 md:p-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-ink tracking-tight">خدمات تخصصی دندانپزشکی</h2>
          <p className="text-caption text-muted">
            فهرست خدمات درمانی و تشخیصی کلینیک (متصل به GET /dental-services/)
          </p>
        </div>

        {hasPerm('book_appointment') && (
          <Button
            variant="teal"
            size="sm"
            onClick={() => setBookingModalOpen(true)}
            icon={<Plus className="w-4 h-4" />}
          >
            رزرو وقت درمان
          </Button>
        )}
      </div>

      {/* Services Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {services.map((service) => (
          <div
            key={service.id}
            className="bg-surface rounded-xl border border-line shadow-2xs p-5 flex flex-col justify-between space-y-4"
          >
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <span className="text-small bg-primary-soft text-primary-deep border border-primary-line/80 px-2 py-0.5 rounded font-mono-numbers font-medium">
                  کد خدمت: #{service.id}
                </span>
                {service.is_active ? (
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

              <div>
                <h3 className="font-bold text-ink text-sm leading-snug">{service.name}</h3>
                {service.description && (
                  <p className="text-caption text-muted mt-2 leading-relaxed">
                    {service.description}
                  </p>
                )}
              </div>
            </div>

            <div className="pt-3 border-t border-line flex items-center justify-between">
              <span className="text-small text-faint">
                قابل انتخاب در رزرو آنلاین و دستیار هوشمند
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

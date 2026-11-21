import React, { useMemo, useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/EmptyState';
import { AppointmentBookingModal } from '../appointments/AppointmentBookingModal';
import { InfoBanner, PageHeader, Segmented, StatCard } from '../common/ui';
import {
  CalendarPlus,
  CheckCircle2,
  Phone,
  Search,
  Sparkles,
  Stethoscope,
  Users,
  XCircle,
} from 'lucide-react';

interface TeamViewProps {
  onNavigate: (view: string) => void;
}

type TeamTab = 'doctors' | 'services';

export const TeamView: React.FC<TeamViewProps> = ({ onNavigate }) => {
  const { doctors, services } = useClinic();
  const { currentUser, hasPerm } = useAuth();
  const [tab, setTab] = useState<TeamTab>('doctors');
  const [search, setSearch] = useState('');
  const [bookingOpen, setBookingOpen] = useState(false);
  const [prefill, setPrefill] = useState<{ doctorId?: number; serviceId?: number }>({});

  const canBook =
    hasPerm('book_appointment') &&
    (currentUser?.role !== 'patient' || Boolean(currentUser?.patient));

  const activeDoctors = doctors.filter((doctor) => doctor.is_active);
  const activeServices = services.filter((service) => service.is_active);
  const specialties = new Set(activeDoctors.map((doctor) => doctor.specialty).filter(Boolean));

  const filteredDoctors = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return activeDoctors;
    return activeDoctors.filter(
      (doctor) =>
        doctor.full_name.toLowerCase().includes(query) ||
        (doctor.specialty || '').toLowerCase().includes(query) ||
        (doctor.phone || '').includes(query)
    );
  }, [activeDoctors, search]);

  const filteredServices = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return activeServices;
    return activeServices.filter(
      (service) =>
        service.name.toLowerCase().includes(query) ||
        (service.description || '').toLowerCase().includes(query)
    );
  }, [activeServices, search]);

  const openBooking = (options: { doctorId?: number; serviceId?: number } = {}) => {
    setPrefill(options);
    setBookingOpen(true);
  };

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="همراهان لبخند شما"
        subtitle="کادر درمان و خدمات قابل ارائه کلینیک؛ فهرست مستقیماً از سرور خوانده می‌شود."
        action={
          canBook ? (
            <Button
              size="md"
              onClick={() => openBooking()}
              icon={<CalendarPlus className="w-4 h-4" />}
            >
              رزرو نوبت
            </Button>
          ) : undefined
        }
      />

      <div className="d-stat-band grid grid-cols-2 xl:grid-cols-4 mb-5">
        <StatCard
          icon={<Stethoscope className="w-[18px] h-[18px]" />}
          label="پزشکان فعال"
          value={String(activeDoctors.length).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)])}
          hint={`از ${doctors.length} پزشک ثبت‌شده`}
        />
        <StatCard
          icon={<Sparkles className="w-[18px] h-[18px]" />}
          label="خدمات فعال"
          value={String(activeServices.length).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)])}
          hint={`از ${services.length} خدمت ثبت‌شده`}
          tone="soft"
        />
        <StatCard
          icon={<Users className="w-[18px] h-[18px]" />}
          label="تخصص‌های موجود"
          value={String(specialties.size).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)])}
          hint="بر اساس تخصص ثبت‌شده پزشکان"
        />
        <StatCard
          icon={<CalendarPlus className="w-[18px] h-[18px]" />}
          label="امکان رزرو"
          value={canBook ? 'فعال' : 'غیرفعال'}
          hint={canBook ? 'بر اساس دسترسی حساب شما' : 'نیازمند پرونده بیمار و دسترسی رزرو'}
          tone="ai"
        />
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <Segmented
          options={[
            { value: 'doctors', label: 'پزشکان', count: activeDoctors.length },
            { value: 'services', label: 'خدمات', count: activeServices.length },
          ]}
          value={tab}
          onChange={(value) => setTab(value as TeamTab)}
        />
        <div className="d-search w-full sm:w-72">
          <Search className="w-4 h-4" />
          <input
            className="d-input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={tab === 'doctors' ? 'جستجوی پزشک یا تخصص...' : 'جستجوی خدمت...'}
            aria-label="جستجو"
          />
        </div>
      </div>

      {tab === 'doctors' ? (
        filteredDoctors.length === 0 ? (
          <EmptyState
            icon={<Stethoscope className="w-5 h-5" />}
            title="پزشکی یافت نشد"
            description={
              activeDoctors.length === 0
                ? 'هیچ پزشک فعالی در سامانه ثبت نشده است.'
                : 'عبارت جستجو با هیچ پزشکی مطابقت ندارد.'
            }
          />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredDoctors.map((doctor) => (
              <article key={doctor.id} className="d-card p-5 flex flex-col hover:border-primary-line transition-colors">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-12 h-12 rounded-[3px] bg-surface-muted border border-line text-ink-soft flex items-center justify-center text-[17px] font-extrabold shrink-0">
                      {doctor.full_name.charAt(0)}
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-small font-bold text-ink truncate">
                        {doctor.full_name}
                      </h3>
                      <p className="text-caption text-muted mt-1 truncate">{doctor.specialty}</p>
                    </div>
                  </div>
                  <Badge variant={doctor.is_active ? 'success' : 'neutral'} dot>
                    {doctor.is_active ? 'فعال' : 'غیرفعال'}
                  </Badge>
                </div>

                <div className="mt-4 pt-4 border-t border-line-soft space-y-2 text-caption text-muted">
                  <div className="flex items-center gap-2">
                    <Stethoscope className="w-3.5 h-3.5 text-faint" />
                    <span>تخصص: {doctor.specialty || 'ثبت نشده'}</span>
                  </div>
                  {doctor.phone && (
                    <div className="flex items-center gap-2">
                      <Phone className="w-3.5 h-3.5 text-faint" />
                      <span dir="ltr" className="tabular-nums">
                        {doctor.phone}
                      </span>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    {doctor.is_active ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-primary" />
                    ) : (
                      <XCircle className="w-3.5 h-3.5 text-danger" />
                    )}
                    <span>{doctor.is_active ? 'قابل انتخاب برای نوبت' : 'در حال حاضر غیرفعال'}</span>
                  </div>
                </div>

                {canBook && doctor.is_active && (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="w-full mt-4"
                    onClick={() => openBooking({ doctorId: doctor.id })}
                    icon={<CalendarPlus className="w-3.5 h-3.5" />}
                  >
                    رزرو با این پزشک
                  </Button>
                )}
              </article>
            ))}
          </div>
        )
      ) : filteredServices.length === 0 ? (
        <EmptyState
          icon={<Sparkles className="w-5 h-5" />}
          title="خدمتی یافت نشد"
          description={
            activeServices.length === 0
              ? 'هیچ خدمت فعالی در سامانه ثبت نشده است.'
              : 'عبارت جستجو با هیچ خدمتی مطابقت ندارد.'
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredServices.map((service) => (
            <article key={service.id} className="d-card p-5 flex flex-col hover:border-primary-line transition-colors">
              <div className="flex items-start justify-between gap-3">
                <span className="d-icon-ring">
                  <Sparkles className="w-4 h-4" />
                </span>
                <Badge variant={service.is_active ? 'success' : 'neutral'} dot>
                  {service.is_active ? 'فعال' : 'غیرفعال'}
                </Badge>
              </div>
              <h3 className="text-small font-bold text-ink mt-3">{service.name}</h3>
              <p className="text-caption text-muted mt-1.5 leading-6 flex-1">
                {service.description || 'توضیحی برای این خدمت در سرور ثبت نشده است.'}
              </p>
              {canBook && service.is_active && (
                <Button
                  size="sm"
                  variant="secondary"
                  className="w-full mt-4"
                  onClick={() => openBooking({ serviceId: service.id })}
                  icon={<CalendarPlus className="w-3.5 h-3.5" />}
                >
                  رزرو این خدمت
                </Button>
              )}
            </article>
          ))}
        </div>
      )}

      <div className="mt-5">
        <InfoBanner tone="info" icon={<Sparkles className="w-4 h-4" />}>
          تعرفه، مدت زمان و پوشش بیمه در پاسخ‌های فعلی سرور ارائه نمی‌شود؛ بنابراین در این صفحه
          نمایش داده نمی‌شوند. برای هماهنگی، با دستیار گفتگو کنید یا با پذیرش تماس بگیرید.
          <button
            type="button"
            onClick={() => onNavigate('agent')}
            className="mr-1 font-bold underline"
          >
            گفتگو با دستیار
          </button>
        </InfoBanner>
      </div>

      <AppointmentBookingModal
        isOpen={bookingOpen}
        onClose={() => setBookingOpen(false)}
        initialDoctorId={prefill.doctorId}
        initialServiceId={prefill.serviceId}
      />
    </div>
  );
};

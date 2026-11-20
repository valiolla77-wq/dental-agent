import React, { useEffect, useState } from 'react';
import { CLINIC_NAME } from '../../config';
import { apiClient } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { Button } from '../common/Button';
import { toLatinDigits } from '../../utils/persianDate';
import { OtpChannel } from '../../types';
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  Building2,
  CalendarDays,
  CheckCircle2,
  ExternalLink,
  KeyRound,
  Lock,
  Phone,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Users,
} from 'lucide-react';

/**
 * Two enforced doors share this screen:
 *  - patient portal (/app): OTP-first, staff accounts are rejected by the API
 *  - staff portal (/staff): password-only for admin/receptionist/doctor
 */
export const LoginView: React.FC = () => {
  const { loginWithPassword, requestOtp, verifyOtp, portal } = useAuth();
  const isStaffPortal = portal === 'staff';
  const [method, setMethod] = useState<'password' | 'otp'>(
    isStaffPortal ? 'password' : 'otp'
  );
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [devOtpHint, setDevOtpHint] = useState<string | null>(null);
  const [otpChannel, setOtpChannel] = useState<OtpChannel | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const isBaleChannel = otpChannel?.provider === 'bale';

  // Which channel delivers the code (Bale bot, SMS, ...). Configuration-level
  // only; a failure keeps the neutral default wording so the form never breaks.
  useEffect(() => {
    if (isStaffPortal) return;
    let cancelled = false;
    apiClient
      .getOtpChannel()
      .then((channel) => {
        if (!cancelled) setOtpChannel(channel);
      })
      .catch(() => {
        /* Older backend or unreachable server: keep neutral wording. */
      });
    return () => {
      cancelled = true;
    };
  }, [isStaffPortal]);

  const normalizedPhone = () => toLatinDigits(phone).replace(/\D/g, '');

  const handlePasswordSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setErrorMsg(null);

    const safePhone = normalizedPhone();
    if (!safePhone || !password.trim()) {
      setErrorMsg('لطفاً شماره تلفن همراه و کلمه عبور را وارد کنید.');
      return;
    }

    setIsLoading(true);
    try {
      await loginWithPassword({ phone: safePhone, password });
    } catch (err: any) {
      setErrorMsg(err.message || 'ورود به سامانه ناکام ماند.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRequestOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    setErrorMsg(null);

    const safePhone = normalizedPhone();
    if (!safePhone) {
      setErrorMsg('لطفاً شماره تلفن همراه را وارد کنید.');
      return;
    }

    setIsLoading(true);
    try {
      const hint = await requestOtp({ phone: safePhone });
      setOtpSent(true);
      setOtpCode('');
      setDevOtpHint(hint ? `کد توسعه (فقط محیط توسعه): ${hint}` : null);
    } catch (err: any) {
      setErrorMsg(err.message || 'ارسال کد یک‌بارمصرف ناکام ماند.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleResendOtp = async () => {
    setErrorMsg(null);
    const safePhone = normalizedPhone();
    if (!safePhone) {
      setErrorMsg('شماره تلفن همراه در دسترس نیست.');
      return;
    }
    setIsLoading(true);
    try {
      const hint = await requestOtp({ phone: safePhone });
      setOtpCode('');
      setDevOtpHint(hint ? `کد توسعه (فقط محیط توسعه): ${hint}` : null);
    } catch (err: any) {
      setErrorMsg(err.message || 'ارسال دوباره کد ناکام ماند.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    setErrorMsg(null);

    const safeCode = toLatinDigits(otpCode).replace(/\D/g, '');
    if (!safeCode) {
      setErrorMsg('لطفاً کد تأیید دریافتی را وارد کنید.');
      return;
    }

    setIsLoading(true);
    try {
      await verifyOtp({ phone: normalizedPhone(), code: safeCode });
    } catch (err: any) {
      setErrorMsg(err.message || 'کد تأیید نامعتبر است یا منقضی شده است.');
    } finally {
      setIsLoading(false);
    }
  };

  const headline = isStaffPortal ? 'ورود پرسنل کلینیک' : 'ورود به حساب';
  const intro = isStaffPortal
    ? 'با شماره تلفن سازمانی و کلمه عبور خود وارد فضای کار شوید. حساب‌های بیمار از این درگاه پذیرفته نمی‌شوند.'
    : 'با شماره تلفن ثبت‌شده در کلینیک وارد شوید؛ کد یک‌بارمصرف برای شما ارسال می‌شود.';

  return (
    <div className="min-h-screen bg-canvas flex" dir="rtl">
      {/* Brand panel */}
      <aside className="hidden lg:flex w-[46%] max-w-[640px] bg-primary text-on-accent flex-col justify-between p-10 xl:p-14 relative overflow-hidden">
        <div className="absolute -top-24 -left-24 w-[340px] h-[340px] rounded-full border border-surface/10" />
        <div className="absolute top-10 -left-10 w-[220px] h-[220px] rounded-full border border-surface/10" />
        <div className="absolute -bottom-32 -right-20 w-[420px] h-[420px] rounded-full bg-primary-deep/40" />
        <div className="absolute bottom-24 right-16 w-24 h-24 rounded-full border border-surface/10" />

        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-[14px] bg-surface/12 border border-surface/25 flex items-center justify-center">
              <Building2 className="w-5 h-5 text-on-accent" />
            </div>
            <div>
              <div className="text-heading font-extrabold leading-6">{CLINIC_NAME}</div>
              <div className="text-small text-on-accent/70 mt-0.5">سامانه نوبت‌دهی و مدیریت کلینیک</div>
            </div>
          </div>

          <h1 className="text-[32px] xl:text-[38px] font-extrabold leading-[1.5] mt-16 max-w-md">
            {isStaffPortal ? (
              <>
                کلینیک،
                <br />
                از پشت صحنه
              </>
            ) : (
              <>
                هر لبخند،
                <br />
                یک شروع خوب
              </>
            )}
          </h1>
          <p className="text-small text-on-accent/75 leading-7 mt-4 max-w-sm">
            {isStaffPortal
              ? 'مدیریت نوبت‌ها، پرونده بیماران، پزشکان و پرسنل؛ همراه با دستیار هوشمند فارسی.'
              : 'نوبت‌دهی، پرونده بیماران و دستیار هوشمند فارسی؛ همه در یک‌جا.'}
          </p>

          <div className="mt-10 space-y-3.5 max-w-sm">
            {(isStaffPortal
              ? [
                  {
                    icon: CalendarDays,
                    title: 'میز کار روزانه',
                    text: 'نوبت‌های امروز، پرونده‌های ناقص و بار کاری پزشکان را یک‌جا ببینید.',
                  },
                  {
                    icon: Users,
                    title: 'مدیریت پرسنل و دسترسی‌ها',
                    text: 'سمت‌ها را ارتقا دهید، دسترسی هر حساب را تنظیم و تغییرات را پیگیری کنید.',
                  },
                  {
                    icon: Bot,
                    title: 'دستیار عاملمحور',
                    text: 'هیچ نوشتنی بدون تأیید صریح شما ثبت نمی‌شود؛ همهٔ ابزارها مجاز و محدود هستند.',
                  },
                ]
              : [
                  {
                    icon: CalendarDays,
                    title: 'نوبت‌دهی در چند ضربه',
                    text: 'زمان‌های خالی هر پزشک را ببینید و نزدیک‌ترین زمان را انتخاب کنید.',
                  },
                  {
                    icon: Users,
                    title: 'پرونده بیماران',
                    text: 'پرونده و سوابق مراجعه فقط برای افراد مجاز قابل مشاهده است.',
                  },
                  {
                    icon: Bot,
                    title: 'دستیار فارسی',
                    text: 'نوبت‌ها را با گفتگو بگیرید یا لغو کنید؛ هر تغییر قبل از ثبت از شما تأیید می‌گیرد.',
                  },
                ]
            ).map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.title}
                  className="flex items-start gap-3 bg-surface/8 border border-surface/12 rounded-[12px] px-3.5 py-3"
                >
                  <span className="w-8 h-8 rounded-full bg-surface/12 border border-surface/20 flex items-center justify-center shrink-0">
                    <Icon className="w-3.5 h-3.5 text-primary-line" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-small font-bold">{item.title}</span>
                    <span className="block text-caption text-on-accent/65 leading-5 mt-0.5">
                      {item.text}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="relative flex items-center gap-2 text-caption text-on-accent/55">
          <ShieldCheck className="w-3.5 h-3.5" />
          اطلاعات شما محافظت می‌شود و فقط برای افراد مجاز نمایش داده می‌شود.
        </div>
      </aside>

      {/* Form panel */}
      <main className="flex-1 flex flex-col justify-center items-center px-4 sm:px-8 py-10">
        <div className="w-full max-w-[420px] d-fade">
          <div className="lg:hidden flex items-center gap-2.5 mb-7">
            <div className="w-10 h-10 rounded-[12px] bg-primary-soft border border-primary-line text-primary flex items-center justify-center">
              <Building2 className="w-5 h-5" />
            </div>
            <div>
              <div className="text-body font-bold text-ink">{CLINIC_NAME}</div>
              <div className="text-small text-faint mt-0.5">سامانه نوبت‌دهی و مدیریت کلینیک</div>
            </div>
          </div>

          <div className="mb-6">
            {isStaffPortal ? (
              <div className="inline-flex items-center gap-1.5 text-caption font-bold text-primary-deep bg-primary-soft border border-primary-line rounded-full px-2.5 py-1 mb-3">
                <Stethoscope className="w-3 h-3" />
                درگاه پرسنل
              </div>
            ) : (
              <div className="inline-flex items-center gap-1.5 text-caption font-bold text-ai bg-ai-soft border border-ai-line rounded-full px-2.5 py-1 mb-3">
                <Sparkles className="w-3 h-3" />
                درگاه بیماران
              </div>
            )}
            <h2 className="text-[26px] font-extrabold text-ink leading-[1.4]">{headline}</h2>
            <p className="text-small text-muted mt-2 leading-6">{intro}</p>
          </div>

          <div className="d-card p-5 sm:p-6">
            {/* Method tabs — the staff door is password-only by design */}
            {!isStaffPortal && (
              <div className="d-segment w-full mb-5">
                <button
                  type="button"
                  role="tab"
                  aria-selected={method === 'otp'}
                  onClick={() => {
                    setMethod('otp');
                    setErrorMsg(null);
                  }}
                  className={`flex-1 ${method === 'otp' ? 'active' : ''}`}
                >
                  کد یک‌بارمصرف
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={method === 'password'}
                  onClick={() => {
                    setMethod('password');
                    setErrorMsg(null);
                  }}
                  className={`flex-1 ${method === 'password' ? 'active' : ''}`}
                >
                  رمز عبور
                </button>
              </div>
            )}

            {errorMsg && (
              <div className="d-soft-danger px-3 py-2.5 mb-4 text-caption text-danger flex items-start gap-2">
                <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span className="leading-5">{errorMsg}</span>
              </div>
            )}

            {/* Bale channel: one-time setup card (open bot → share contact) */}
            {!isStaffPortal && method === 'otp' && isBaleChannel && (
              <div className="d-soft-teal px-3 py-3 mb-4 text-caption text-primary-deep leading-5">
                <div className="flex items-center gap-1.5 font-bold mb-1.5">
                  <Bot className="w-3.5 h-3.5" />
                  دریافت کد از طریق بات بله
                </div>
                <ol className="list-decimal pe-4 space-y-1">
                  <li>بات کلینیک را در بله باز کنید و Start بزنید.</li>
                  <li>دکمه «اشتراک شماره تماس» را بزنید تا شماره شما متصل شود.</li>
                  <li>به همین صفحه برگردید و کد تأیید را درخواست کنید.</li>
                </ol>
                {otpChannel?.bot_url && (
                  <a
                    href={otpChannel.bot_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2.5 inline-flex items-center gap-1.5 font-bold text-primary hover:text-primary-deep hover:underline"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    باز کردن بات کلینیک در بله
                  </a>
                )}
              </div>
            )}

            {method === 'password' || isStaffPortal ? (
              <form onSubmit={handlePasswordSubmit} className="space-y-4">
                <div>
                  <label className="d-label" htmlFor="login-phone">
                    شماره تلفن همراه
                  </label>
                  <div className="relative">
                    <Phone className="w-4 h-4 text-faint absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      id="login-phone"
                      type="tel"
                      value={phone}
                      onChange={(event) => setPhone(event.target.value)}
                      placeholder="۰۹۱۲۱۲۳۴۵۶۷"
                      autoComplete="tel"
                      className="d-input !pr-10 tabular-nums"
                      dir="ltr"
                      required
                    />
                  </div>
                </div>

                <div>
                  <label className="d-label" htmlFor="login-password">
                    کلمه عبور
                  </label>
                  <div className="relative">
                    <Lock className="w-4 h-4 text-faint absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      id="login-password"
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="••••••••"
                      autoComplete="current-password"
                      className="d-input !pr-10"
                      required
                    />
                  </div>
                </div>

                <Button type="submit" size="lg" className="w-full" isLoading={isLoading}>
                  ورود به فضای کار
                </Button>

                {!isStaffPortal && (
                  <p className="text-caption text-faint leading-5 text-center">
                    حساب بیمار با رمز عبور؟ این تب هم برای شما فعال است.
                  </p>
                )}
              </form>
            ) : !otpSent ? (
              <form onSubmit={handleRequestOtp} className="space-y-4">
                <div>
                  <label className="d-label" htmlFor="otp-phone">
                    شماره تلفن همراه
                  </label>
                  <div className="relative">
                    <Phone className="w-4 h-4 text-faint absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      id="otp-phone"
                      type="tel"
                      value={phone}
                      onChange={(event) => setPhone(event.target.value)}
                      placeholder="۰۹۱۲۱۲۳۴۵۶۷"
                      autoComplete="tel"
                      className="d-input !pr-10 tabular-nums"
                      dir="ltr"
                      required
                    />
                  </div>
                </div>

                <p className="text-caption text-faint leading-5">
                  {isBaleChannel
                    ? 'کد یک‌بارمصرف از طریق بات بله به شماره متصل‌شده شما ارسال می‌شود. اگر حساب ندارید، ابتدا از پذیرش کلینیک بخواهید حساب شما را ایجاد کند.'
                    : 'کد یک‌بارمصرف به همین شماره ارسال می‌شود. اگر حساب ندارید، ابتدا از پذیرش کلینیک بخواهید حساب شما را ایجاد کند.'}
                </p>

                <Button type="submit" size="lg" className="w-full" isLoading={isLoading}>
                  ارسال کد تأیید
                </Button>
              </form>
            ) : (
              <form onSubmit={handleVerifyOtp} className="space-y-4">
                <div className="d-soft-teal px-3 py-2.5 flex items-center justify-between gap-2">
                  <span className="text-caption text-primary-deep flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {isBaleChannel ? (
                      <span>
                        کد تأیید به بات بله شما ارسال شد؛ شماره متصل‌شده:{' '}
                        <strong className="tabular-nums" dir="ltr">{toLatinDigits(phone)}</strong>
                      </span>
                    ) : (
                      <span>
                        کد ارسال‌شده به <strong className="tabular-nums" dir="ltr">{toLatinDigits(phone)}</strong>
                      </span>
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setOtpSent(false);
                      setOtpCode('');
                      setDevOtpHint(null);
                      setErrorMsg(null);
                    }}
                    className="text-caption font-semibold text-primary hover:underline shrink-0"
                  >
                    ویرایش
                  </button>
                </div>

                {devOtpHint && (
                  <div className="d-soft-warn px-3 py-2 text-caption text-warn leading-5">
                    {devOtpHint}
                  </div>
                )}

                <div>
                  <label className="d-label" htmlFor="otp-code">
                    کد تأیید ۶ رقمی
                  </label>
                  <div className="relative">
                    <KeyRound className="w-4 h-4 text-faint absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      id="otp-code"
                      type="text"
                      value={otpCode}
                      onChange={(event) => setOtpCode(event.target.value)}
                      placeholder="۱۲۳۴۵۶"
                      maxLength={6}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      className="d-input !pr-10 text-center tracking-[0.35em] tabular-nums !text-heading"
                      dir="ltr"
                      required
                    />
                  </div>
                </div>

                <Button type="submit" size="lg" className="w-full" isLoading={isLoading}>
                  تأیید و ورود
                </Button>

                <button
                  type="button"
                  onClick={handleResendOtp}
                  disabled={isLoading}
                  className="w-full text-center text-caption text-muted hover:text-primary disabled:opacity-50"
                >
                  ارسال دوباره کد
                </button>
              </form>
            )}
          </div>

          <div className="mt-5 flex items-center justify-center gap-1.5 text-caption text-faint">
            <ShieldCheck className="w-3.5 h-3.5" />
            ورود امن به حساب شما
          </div>

          {/* Cross-portal link: the other door is one click away */}
          {isStaffPortal ? (
            <a
              href="/app"
              className="mt-3 mx-auto flex items-center justify-center gap-1 text-caption font-semibold text-primary hover:text-primary-deep"
            >
              بیمار هستید؟ ورود از درگاه بیماران
              <ArrowLeft className="w-3 h-3" />
            </a>
          ) : (
            <a
              href="/staff"
              className="mt-3 mx-auto flex items-center justify-center gap-1 text-caption font-semibold text-primary hover:text-primary-deep"
            >
              پرسنل کلینیک هستید؟ ورود از درگاه پرسنل
              <ArrowLeft className="w-3 h-3" />
            </a>
          )}
        </div>
      </main>
    </div>
  );
};

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { MeResponse, LoginRequest, OtpRequest, OtpVerifyRequest } from '../types';
import { apiClient, ApiError } from '../api/client';
import { hasPermission, Permission } from '../utils/rbac';

export type PortalKind = 'patient' | 'staff';

interface AuthContextType {
  currentUser: MeResponse | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** The saved session could not be checked because the server is unreachable. */
  connectionLost: boolean;
  /** Which door the person came in through (drives logout behaviour). */
  portal: PortalKind;
  loginWithPassword: (data: LoginRequest) => Promise<void>;
  requestOtp: (data: OtpRequest) => Promise<string | undefined>;
  verifyOtp: (data: OtpVerifyRequest) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  hasPerm: (perm: Permission) => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode; portal?: PortalKind }> = ({
  children,
  portal: portalProp,
}) => {
  // The portal is chosen once at mount from the URL pathname (/staff = staff
  // door) unless the app overrides it explicitly (e.g. in tests).
  const [portal] = useState<PortalKind>(
    () => portalProp || detectPortalFromPath()
  );
  const [currentUser, setCurrentUser] = useState<MeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [connectionLost, setConnectionLost] = useState(false);

  const refreshUser = useCallback(async () => {
    setIsLoading(true);
    try {
      if (!apiClient.getToken()) {
        setCurrentUser(null);
        setConnectionLost(false);
        return;
      }
      const me = await apiClient.getMe();
      setConnectionLost(false);
      if (me && me.is_active) {
        setCurrentUser(me);
      } else {
        apiClient.setToken(null);
        setCurrentUser(null);
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        // The server rejected the session: sign out.
        apiClient.setToken(null);
        setCurrentUser(null);
        setConnectionLost(false);
      } else {
        // A network blip must not sign anyone out; keep the token and let the
        // person retry.
        setConnectionLost(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const loginWithPassword = async (data: LoginRequest) => {
    setIsLoading(true);
    try {
      // Each portal posts to its own enforced door: the staff door rejects
      // patient accounts and the patient door rejects staff accounts.
      if (portal === 'staff') {
        await apiClient.staffLogin({ phone: data.phone, password: data.password });
      } else {
        await apiClient.login({ ...data, portal: 'patient' });
      }
      // Strictly resolve user profile and role from /auth/me
      const me = await apiClient.getMe();
      if (!me.is_active) {
        throw new Error('حساب کاربری شما غیرفعال شده است. لطفاً با مدیریت تماس بگیرید.');
      }
      setCurrentUser(me);
    } finally {
      setIsLoading(false);
    }
  };

  const requestOtp = async (data: OtpRequest): Promise<string | undefined> => {
    const res = await apiClient.requestOtp(data);
    return res.dev_otp || undefined;
  };

  const verifyOtp = async (data: OtpVerifyRequest) => {
    setIsLoading(true);
    try {
      await apiClient.verifyOtp(data);
      const me = await apiClient.getMe();
      if (!me.is_active) {
        throw new Error('حساب کاربری شما غیرفعال شده است.');
      }
      setCurrentUser(me);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    apiClient.setToken(null);
    setCurrentUser(null);
  };

  const hasPerm = (perm: Permission): boolean => {
    if (!currentUser) return false;
    return hasPermission(currentUser.role, perm);
  };

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        isAuthenticated: !!currentUser,
        isLoading,
        connectionLost,
        portal,
        loginWithPassword,
        requestOtp,
        verifyOtp,
        logout,
        refreshUser,
        hasPerm,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

/** Decide the login door from the browser path: /staff = staff portal. */
export function detectPortalFromPath(pathname?: string): PortalKind {
  const path = pathname ?? (typeof window !== 'undefined' ? window.location.pathname : '/');
  return path.startsWith('/staff') ? 'staff' : 'patient';
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

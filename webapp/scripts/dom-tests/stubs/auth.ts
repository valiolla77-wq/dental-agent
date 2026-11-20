// Test double for AuthContext: the test sets globalThis.__auth before rendering.
export const useAuth = () => (globalThis as any).__auth;

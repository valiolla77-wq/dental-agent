// Test double for ClinicContext: the test sets globalThis.__clinic before rendering.
export const useClinic = () => (globalThis as any).__clinic;

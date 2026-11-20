/** Product-level constants shared by the UI. */

export const PRODUCT_NAME = 'Dental Agent';

/**
 * Name shown in the header and on the sign-in page. A clinic sets
 * ``VITE_CLINIC_NAME`` at build time; otherwise the product name is used, so
 * nobody else's clinic name is ever shown by default.
 */
export const CLINIC_NAME =
  ((import.meta.env.VITE_CLINIC_NAME as string | undefined) || '').trim() || PRODUCT_NAME;

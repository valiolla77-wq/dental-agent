/** Helpers for rendering assistant messages. */

const collapse = (text: string) => text.replace(/[\u200c\s]+/g, ' ').trim();

/**
 * Whether a bubble's text only repeats the sentence the confirmation card
 * already shows. The server sends the same prompt as the message body and as
 * ``confirmation_prompt``; rendering both reads as a stutter.
 */
export function repeatsConfirmationPrompt(
  content: string,
  prompt: string | null | undefined,
  hasConfirmationCard: boolean
): boolean {
  if (!hasConfirmationCard || !prompt) return false;
  return collapse(content) === collapse(prompt);
}

/**
 * After the person approves a write, a failed request may still have been
 * applied on the server (the response was lost, a proxy timed out, a 5xx came
 * back late). Resending would risk a duplicate, so these outcomes are treated
 * as *unknown*. Anything else (400-499) is a definite refusal.
 */
export function isOutcomeUncertain(status: number): boolean {
  return status === 0 || status === 408 || status >= 500;
}

export const OUTCOME_UNKNOWN_MESSAGE =
  'نتیجهٔ این تأیید مشخص نیست؛ برای جلوگیری از ثبت تکراری، درخواست دوباره ارسال نشد. ' +
  'وضعیت را در بخش «نوبت‌ها» ببینید، یا از دستیار بخواهید «نوبت‌های من را نشان بده».';

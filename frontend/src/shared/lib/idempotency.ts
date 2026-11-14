// A client-generated key for create and replace. Reuse the SAME key when retrying one attempt;
// make a new one when the customer changes the terms.
export const newIdempotencyKey = () => `customer-${crypto.randomUUID()}`;

export function ErrorMessage({ message }: { message: string }) {
  return message ? (
    <div
      className="error my-4 rounded-lg border border-error/20 bg-error-container px-4 py-3 text-body-sm text-on-error-container"
      role="alert"
    >
      {message}
    </div>
  ) : null;
}

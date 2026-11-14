export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span
      className={`font-headline font-extrabold leading-none tracking-tighter text-deep-ocean-navy ${className}`}
    >
      aimo<span className="text-status-fresh-green">.</span>
    </span>
  );
}

import { useState } from "react";
import type { components } from "../../../shared/api/schema";

type Props = { image: components["schemas"]["RecipeImage"] };

export function RecipeIllustration({ image }: Props) {
  const [failed, setFailed] = useState(false);
  return (
    <figure className="my-space-md w-full max-w-xl">
      {failed ? (
        <p role="status">This illustration is currently unavailable.</p>
      ) : (
        <img
          className="block h-auto w-full rounded-xl bg-surface-container-low"
          src={image.url}
          alt="AI-generated recipe illustration"
          width={image.width}
          height={image.height}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      )}
      <figcaption className="mt-space-sm text-body-sm text-on-surface-variant">
        AI-generated illustration · Actual presentation may vary.
      </figcaption>
    </figure>
  );
}

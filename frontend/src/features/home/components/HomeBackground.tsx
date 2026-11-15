import { useEffect, useState } from "react";
import { homeBackgroundPhoto } from "../model/backgroundPhoto";

// Remembers whether the photo has already been shown, so coming back to Home from another
// page shows it straight away instead of fading in again.
let shown = false;

/** Decorative full-bleed photo behind Home, right of the desktop sidebar. */
export function HomeBackground() {
  const src = homeBackgroundPhoto();
  const [loaded, setLoaded] = useState(shown);
  useEffect(() => {
    if (loaded) return;
    const image = new Image();
    image.onload = () => {
      shown = true;
      setLoaded(true);
    };
    image.src = src;
    return () => {
      image.onload = null;
    };
  }, [loaded, src]);
  return (
    <div className="home-background" aria-hidden="true">
      <div
        className={`home-background-photo ${loaded ? "is-loaded" : ""}`}
        style={loaded ? { backgroundImage: `url("${src}")` } : undefined}
      />
    </div>
  );
}

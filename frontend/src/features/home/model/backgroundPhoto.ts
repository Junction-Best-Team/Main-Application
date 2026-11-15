// Home's background photo. One photo is picked per page load, so it stays the same while the
// buyer moves around the app and changes only on a refresh. The previous pick is skipped so a
// refresh always shows a different photo. Stock photos: see docs/pre-existing-work.md.
const PHOTOS = [
  new URL("../assets/backgrounds/home-1.jpg", import.meta.url).href,
  new URL("../assets/backgrounds/home-2.jpg", import.meta.url).href,
  new URL("../assets/backgrounds/home-3.jpg", import.meta.url).href,
  new URL("../assets/backgrounds/home-4.jpg", import.meta.url).href,
  new URL("../assets/backgrounds/home-5.jpg", import.meta.url).href,
  new URL("../assets/backgrounds/home-6.jpg", import.meta.url).href,
  new URL("../assets/backgrounds/home-7.jpg", import.meta.url).href,
];

const STORAGE_KEY = "aimo-home-background";

function pickPhoto(): string {
  let previous = -1;
  try {
    previous = Number(localStorage.getItem(STORAGE_KEY) ?? -1);
  } catch {
    /* Storage can be blocked; any photo will do. */
  }
  let index = Math.floor(Math.random() * (PHOTOS.length - 1));
  if (previous >= 0 && index >= previous) index += 1;
  try {
    localStorage.setItem(STORAGE_KEY, String(index));
  } catch {
    /* Not remembering the pick only allows a repeat. */
  }
  return PHOTOS[index];
}

let photo: string | null = null;

/** The photo for this page load; picked on first use. */
export function homeBackgroundPhoto(): string {
  photo ??= pickPhoto();
  return photo;
}

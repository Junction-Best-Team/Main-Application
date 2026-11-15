// Home -> chat animation. On send, the message box's controls fade out and an empty card
// (the "ghost", plain DOM so it survives the route change) grows from the box until it
// covers the whole content area, over the photo, ending as the plain page background.
// The chat page (which has no photo) then fades in on that background and removes the
// ghost. Runs while the conversation is being created, so nothing waits on it.

const FADE_MS = 160;
const EXPAND_MS = 480;
const EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";

type Expansion = {
  ghost: HTMLElement;
  composer: HTMLElement;
  faded: Animation[];
  done: Promise<void>;
};

let current: Expansion | null = null;

const reducedMotion = () =>
  matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The content area right of the desktop sidebar: everywhere the photo shows. On phones
 *  the ghost sits under the sticky top bar (see .chat-expand-ghost z-index). */
function contentAreaRect(): DOMRect {
  const desktop = matchMedia("(min-width: 768px)").matches;
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
  const left = desktop ? 15 * rem : 0;
  return new DOMRect(
    left,
    0,
    document.documentElement.clientWidth - left,
    window.innerHeight,
  );
}

const box = (r: DOMRect) => ({
  left: `${r.left}px`,
  top: `${r.top}px`,
  width: `${r.width}px`,
  height: `${r.height}px`,
});

/** Starts the expansion from Home's message box; resolves when the card is full size. */
export function expandComposerToChat(composer: HTMLElement): Promise<void> {
  if (current) return current.done;
  const motion = !reducedMotion();
  const fade = (el: Element, delay = 0) =>
    el.animate([{ opacity: 1 }, { opacity: 0 }], {
      duration: motion ? FADE_MS : 0,
      delay: motion ? delay : 0,
      easing: "ease-out",
      fill: "forwards",
    });

  // Buttons and text go first, then the heading; the deliveries card slides down off-screen.
  const schedule = document.querySelector(".home-schedule");
  const faded = [
    ...Array.from(composer.children).map((el) => fade(el)),
    ...Array.from(
      document.querySelectorAll(".home-intro, .home-demo-note"),
    ).map((el) => fade(el, 60)),
    ...(schedule
      ? [
          schedule.animate(
            [
              { transform: getComputedStyle(schedule).transform },
              { transform: "translateY(100dvh)" },
            ],
            {
              duration: motion ? 650 : 0,
              easing: "cubic-bezier(0.7, 0, 0.84, 0)",
              fill: "forwards",
            },
          ),
        ]
      : []),
  ];

  const from = composer.getBoundingClientRect();
  const style = getComputedStyle(composer);
  const ghost = document.createElement("div");
  ghost.className = "chat-expand-ghost";
  ghost.setAttribute("aria-hidden", "true");
  Object.assign(ghost.style, box(from), {
    borderRadius: style.borderRadius,
    background: style.backgroundColor,
    opacity: "0",
  });
  document.body.appendChild(ghost);

  const done = (async () => {
    await Promise.all(
      faded.slice(0, composer.children.length).map((a) => a.finished),
    );
    ghost.style.opacity = "1";
    composer.style.visibility = "hidden";
    const canvas = getComputedStyle(document.documentElement)
      .getPropertyValue("--color-canvas")
      .trim();
    const grow = ghost.animate(
      [
        {
          ...box(from),
          backgroundColor: style.backgroundColor,
          borderRadius: style.borderRadius,
        },
        {
          ...box(contentAreaRect()),
          backgroundColor: canvas,
          borderRadius: "0px",
          boxShadow: "none",
        },
      ],
      { duration: motion ? EXPAND_MS : 0, easing: EASE, fill: "forwards" },
    );
    await grow.finished.catch(() => undefined);
  })();

  current = { ghost, composer, faded, done };
  return done;
}

/** Sending failed: shrink back and show Home again. */
export function cancelChatExpansion() {
  const expansion = current;
  if (!expansion) return;
  current = null;
  const { ghost, composer, faded } = expansion;
  const restore = () => {
    ghost.remove();
    composer.style.visibility = "";
    faded.forEach((a) => a.cancel());
  };
  ghost.getAnimations().forEach((a) => {
    a.playbackRate = -1.6;
  });
  const reverse = ghost.getAnimations()[0];
  if (reverse && !reducedMotion()) {
    reverse.play();
    void reverse.finished.then(restore, restore);
  } else restore();
}

/** Resolves when the card is full size (at once if nothing is expanding). */
export function chatExpansionDone(): Promise<void> {
  return current?.done ?? Promise.resolve();
}

/** True while a Home expansion is waiting for the chat page. */
export function hasChatExpansion() {
  return current !== null;
}

/** Called by the chat page once it is in place: the full-screen card fades away over it. */
export function finishChatExpansion() {
  const expansion = current;
  if (!expansion) return;
  current = null;
  void expansion.done.then(() => {
    const out = expansion.ghost.animate([{ opacity: 1 }, { opacity: 0 }], {
      duration: reducedMotion() ? 0 : 280,
      easing: "ease-out",
      fill: "forwards",
    });
    void out.finished.finally(() => expansion.ghost.remove());
  });
}

// ---------- Chat -> Home: the same animation in reverse ----------

let collapse: { ghost: HTMLElement; shrink?: Promise<void> } | null = null;

/** "New request" from a chat: fade the chat out, cover the content area with the
 *  background card, then open Home underneath it (Home shrinks the card, below). */
export function collapseChatToHome(open: () => void) {
  const chat = document.querySelector(".chat-page");
  if (!chat || collapse || reducedMotion()) {
    open();
    return;
  }
  const ghost = document.createElement("div");
  ghost.className = "chat-expand-ghost";
  ghost.setAttribute("aria-hidden", "true");
  Object.assign(ghost.style, box(contentAreaRect()), {
    borderRadius: "0px",
    boxShadow: "none",
    background: getComputedStyle(document.documentElement)
      .getPropertyValue("--color-canvas")
      .trim(),
    opacity: "0",
  });
  document.body.appendChild(ghost);
  collapse = { ghost };
  const fade = chat.animate([{ opacity: 1 }, { opacity: 0 }], {
    duration: FADE_MS,
    easing: "ease-out",
    fill: "forwards",
  });
  void fade.finished.then(() => {
    ghost.style.opacity = "1";
    open();
  });
}

/** True while a chat collapse is waiting for Home to mount. */
export function hasChatCollapse() {
  return collapse !== null;
}

/** Called by Home once mounted: shrinks the card into the message box, then removes it.
 *  Resolves when Home should fade its own content back in. Safe to call twice. */
export function finishChatCollapse(
  composer: HTMLElement | null,
): Promise<void> {
  const pending = collapse;
  if (!pending) return Promise.resolve();
  pending.shrink ??= (async () => {
    const { ghost } = pending;
    if (composer) {
      const style = getComputedStyle(composer);
      const shrink = ghost.animate(
        [
          {
            ...box(contentAreaRect()),
            backgroundColor: ghost.style.background,
            borderRadius: "0px",
            boxShadow: "none",
          },
          {
            ...box(composer.getBoundingClientRect()),
            backgroundColor: style.backgroundColor,
            borderRadius: style.borderRadius,
          },
        ],
        { duration: EXPAND_MS, easing: EASE, fill: "forwards" },
      );
      await shrink.finished.catch(() => undefined);
    }
    ghost.remove();
    collapse = null;
  })();
  return pending.shrink;
}

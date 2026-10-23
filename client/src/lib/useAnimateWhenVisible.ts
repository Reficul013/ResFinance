import { useEffect, useRef, useState } from "react";

/**
 * Flips to true once the element enters the viewport so entrance animations
 * run when the user can actually see them (not while charts are still off-screen).
 */
export function useAnimateWhenVisible<
  T extends HTMLElement = HTMLDivElement,
>(options?: { rootMargin?: string; threshold?: number }) {
  const ref = useRef<T>(null);
  const [animated, setAnimated] = useState(false);
  const rootMargin = options?.rootMargin ?? "0px 0px -6% 0px";
  const threshold = options?.threshold ?? 0.2;

  useEffect(() => {
    const node = ref.current;
    if (node === null || animated) return;

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduceMotion) {
      setAnimated(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setAnimated(true);
          observer.disconnect();
        }
      },
      { rootMargin, threshold },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [animated, rootMargin, threshold]);

  return { ref, animated };
}

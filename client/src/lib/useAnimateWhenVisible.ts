import { useCallback, useEffect, useState } from "react";

/**
 * Flips to true once the element enters the viewport so entrance animations
 * run when the user can actually see them (not while charts are still off-screen).
 *
 * Uses a callback ref so observation starts when a conditionally rendered
 * element mounts after data loads (e.g. budget list).
 */
export function useAnimateWhenVisible<
  T extends HTMLElement = HTMLDivElement,
>(options?: { rootMargin?: string; threshold?: number }) {
  const [node, setNode] = useState<T | null>(null);
  const [animated, setAnimated] = useState(false);
  const rootMargin = options?.rootMargin ?? "0px 0px -6% 0px";
  const threshold = options?.threshold ?? 0.2;

  const ref = useCallback((element: T | null) => {
    setNode(element);
  }, []);

  useEffect(() => {
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
  }, [animated, node, rootMargin, threshold]);

  return { ref, animated };
}

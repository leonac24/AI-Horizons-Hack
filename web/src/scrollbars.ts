// Marks whichever element is scrolling so CSS can brighten its scrollbar, then fades it after a pause.
const FADE_MS = 900
const timers = new WeakMap<Element, number>()

export function watchScrolling(): void {
  document.addEventListener(
    'scroll',
    (e) => {
      const el = e.target instanceof Element ? e.target : document.documentElement
      el.classList.add('is-scrolling')
      window.clearTimeout(timers.get(el))
      timers.set(el, window.setTimeout(() => el.classList.remove('is-scrolling'), FADE_MS))
    },
    { capture: true, passive: true },
  )
}

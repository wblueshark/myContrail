/**
 * Locale selection.
 *
 * Three dictionaries, one shape: `en` and `ja` are typed as `Copy`, so a key
 * added to `zh` breaks their build until they carry it too. That is the whole
 * mechanism - there is no runtime fallback, because a fallback turns a missing
 * translation into a silently mixed-language screen instead of a build error.
 *
 * The choice also drives `<html lang>`, which selects the CJK font fallback:
 * Barlow has no CJK glyphs, and Japanese must not fall through to a Chinese
 * face.
 */

import { create } from 'zustand'

import { en } from './en'
import { ja } from './ja'
import { type Copy, t as zh } from './zh'

export type Locale = 'zh' | 'en' | 'ja'

export const LOCALES: Array<{ id: Locale; label: string }> = [
  { id: 'zh', label: '中文' },
  { id: 'en', label: 'EN' },
  { id: 'ja', label: '日本語' },
]

const DICTS: Record<Locale, Copy> = { zh, en, ja }
const HTML_LANG: Record<Locale, string> = { zh: 'zh-CN', en: 'en', ja: 'ja' }
const STORAGE_KEY = 'contrail.locale'

function stored(): Locale {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    if (value === 'zh' || value === 'en' || value === 'ja') return value
  } catch {
    // Private browsing: the session default is fine.
  }
  return 'zh'
}

function applyLang(locale: Locale): void {
  document.documentElement.lang = HTML_LANG[locale]
}

interface LocaleState {
  locale: Locale
  setLocale: (locale: Locale) => void
}

export const useLocaleStore = create<LocaleState>((set) => ({
  locale: stored(),
  setLocale: (locale) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, locale)
    } catch {
      // As above: not being able to remember it is not a reason to refuse it.
    }
    applyLang(locale)
    set({ locale })
  },
}))

applyLang(useLocaleStore.getState().locale)

/** The copy for the active locale. Re-renders the caller when it changes. */
export function useCopy(): Copy {
  return DICTS[useLocaleStore((state) => state.locale)]
}

/** For code outside React (formatters, event handlers on module scope). */
export function getCopy(): Copy {
  return DICTS[useLocaleStore.getState().locale]
}

export type { Copy }

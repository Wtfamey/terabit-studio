/**
 * User preferences -- one small store, one localStorage key, no server.
 *
 * A local-first app has to be honest about where settings live: these are
 * machine-local preferences, so they live on this machine (localStorage), not
 * in the account and not in the database. The `.env` next to the app remains
 * the place for machine configuration (ports, GPU layers); this file is only
 * what a user changes while working.
 *
 * Only settings that are actually wired to behaviour are listed. A control
 * that does nothing is worse than no control: it costs trust the first time
 * someone flips it and nothing happens.
 *
 *   provider      - which model backend new builds default to (local first)
 *   temperature   - model temperature for new builds
 *   copyLanguage  - append a language directive to prompts when not "auto"
 *   reduceMotion  - force reduced motion even when the OS does not ask
 */
import { useSyncExternalStore } from 'react';

export type Provider = 'auto' | 'local' | 'openai';

export interface Settings {
  provider: Provider;
  temperature: number;
  copyLanguage: string;
  reduceMotion: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  provider: 'auto',
  temperature: 0.7,
  copyLanguage: 'auto',
  reduceMotion: false,
};

/** Languages the prompt layer and the v3 fine-tune were verified with. The
 *  value is a directive, not a translation table -- the model writes copy in
 *  the language it is asked for, and the brief parser understands Hinglish
 *  and Devanagari input natively. */
export const COPY_LANGUAGES: { value: string; label: string; directive: string }[] = [
  { value: 'auto', label: 'Same as my prompt (recommended)', directive: '' },
  { value: 'en', label: 'English', directive: 'Write all user-facing copy in English.' },
  { value: 'hi', label: 'Hindi (हिंदी, Devanagari)', directive: 'Write all user-facing copy in Hindi (हिंदी), in Devanagari script.' },
  { value: 'hi-Latn', label: 'Hindi in Latin script (Hinglish)', directive: 'Write all user-facing copy in Hindi using Latin script (Hinglish).' },
  { value: 'mr', label: 'Marathi (मराठी)', directive: 'Write all user-facing copy in Marathi (मराठी), in Devanagari script.' },
  { value: 'bn', label: 'Bengali (বাংলা)', directive: 'Write all user-facing copy in Bengali (বাংলা).' },
  { value: 'gu', label: 'Gujarati (ગુજરાતી)', directive: 'Write all user-facing copy in Gujarati (ગુજરાતી).' },
  { value: 'ta', label: 'Tamil (தமிழ்)', directive: 'Write all user-facing copy in Tamil (தமிழ்).' },
];

const KEY = 'terabit.settings.v1';
let current: Settings = read();
const listeners = new Set<() => void>();

function read(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return sanitise({ ...DEFAULT_SETTINGS, ...parsed });
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function sanitise(s: Settings): Settings {
  const temperature = Number.isFinite(s.temperature)
    ? Math.min(1.2, Math.max(0, s.temperature))
    : DEFAULT_SETTINGS.temperature;
  const provider: Provider = (['auto', 'local', 'openai'] as const).includes(s.provider as Provider)
    ? s.provider as Provider
    : DEFAULT_SETTINGS.provider;
  return {
    ...s,
    temperature,
    provider,
    copyLanguage: COPY_LANGUAGES.some(l => l.value === s.copyLanguage)
      ? s.copyLanguage
      : DEFAULT_SETTINGS.copyLanguage,
    reduceMotion: Boolean(s.reduceMotion),
  };
}

export function getSettings(): Settings {
  return current;
}

export function saveSettings(patch: Partial<Settings>): Settings {
  current = sanitise({ ...current, ...patch });
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    // A full or blocked localStorage must not break the page; the value is
    // still live in memory for this session.
  }
  applyMotionPreference(current);
  listeners.forEach((cb) => cb());
  return current;
}

export function resetSettings(): Settings {
  return saveSettings({ ...DEFAULT_SETTINGS });
}

export function subscribeSettings(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function useSettings(): Settings {
  return useSyncExternalStore(subscribeSettings, getSettings, getSettings);
}

/** Screen-reader- and CSS-visible motion preference: the OS setting is the
 *  default (see prefers-reduced-motion in index.css), this forces it on. */
export function applyMotionPreference(s: Settings = current): void {
  try {
    document.documentElement.classList.toggle('force-reduce-motion', s.reduceMotion);
  } catch {
    /* no document (tests) */
  }
}

export function languageDirective(value: string): string {
  return COPY_LANGUAGES.find(l => l.value === value)?.directive || '';
}

/** Compose the prompt the model actually sees: the user's words plus the
 *  language directive, if any. Kept in one place so the queue, the composer
 *  and any future entry point cannot disagree about it. */
export function withLanguageDirective(prompt: string, s: Settings = current): string {
  const directive = languageDirective(s.copyLanguage);
  if (!directive) return prompt;
  return `${prompt.trim()}\n\n${directive}`;
}

applyMotionPreference(current);

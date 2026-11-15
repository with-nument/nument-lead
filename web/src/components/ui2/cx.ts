export type ClassValue = string | false | null | undefined | 0

/**
 * Joins class names, skipping empty ones. v2 components are built so callers never need class
 * conflict resolution, which keeps tailwind-merge (about 9 KB) out of v2 pages and the sign-in page.
 */
export function cx(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(' ')
}

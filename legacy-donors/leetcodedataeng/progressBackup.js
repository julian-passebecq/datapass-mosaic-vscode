export const STORAGE_PREFIX = 'de-coding-reset-v1'
export const BACKUP_FORMAT = 'de-coding-reset-backup'
export const BACKUP_VERSION = 1

function isAppStorageKey(key) {
  return typeof key === 'string' && key.startsWith(`${STORAGE_PREFIX}:`)
}

function assertValidEntry(key, value) {
  if (!isAppStorageKey(key)) throw new Error(`Unexpected storage key: ${key}`)
  if (typeof value !== 'string') throw new Error(`Invalid value for ${key}`)
  JSON.parse(value)
}

function collectAppEntries(storage) {
  const entries = {}
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (!isAppStorageKey(key)) continue
    const value = storage.getItem(key)
    if (value == null) continue
    assertValidEntry(key, value)
    entries[key] = value
  }
  return entries
}

function removeAppEntries(storage) {
  const keys = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (isAppStorageKey(key)) keys.push(key)
  }
  for (const key of keys) storage.removeItem(key)
}

export function collectProgressBackup(storage, exportedAt = new Date().toISOString()) {
  return {
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exportedAt,
    entries: collectAppEntries(storage),
  }
}

export function validateProgressBackup(input) {
  const backup = typeof input === 'string' ? JSON.parse(input) : input
  if (!backup || typeof backup !== 'object' || Array.isArray(backup)) throw new Error('Backup must be a JSON object.')
  if (backup.format !== BACKUP_FORMAT) throw new Error('This file is not a Coding Reset backup.')
  if (backup.version !== BACKUP_VERSION) throw new Error(`Unsupported backup version: ${backup.version}`)
  if (!backup.entries || typeof backup.entries !== 'object' || Array.isArray(backup.entries)) throw new Error('Backup entries are missing.')

  const entries = Object.entries(backup.entries)
  if (entries.length > 1000) throw new Error('Backup contains too many entries.')
  for (const [key, value] of entries) assertValidEntry(key, value)
  return backup
}

export function restoreProgressBackup(storage, input, { replace = false } = {}) {
  const backup = validateProgressBackup(input)
  const entries = Object.entries(backup.entries)
  const previousEntries = collectAppEntries(storage)

  try {
    if (replace) removeAppEntries(storage)
    for (const [key, value] of entries) storage.setItem(key, value)
  } catch (error) {
    try {
      removeAppEntries(storage)
      for (const [key, value] of Object.entries(previousEntries)) storage.setItem(key, value)
    } catch {
      // Preserve the original storage error. A second storage failure means the
      // browser storage itself is unavailable or exhausted.
    }
    throw error
  }

  return entries.length
}

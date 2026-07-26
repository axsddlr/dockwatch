import { useState, useEffect } from 'react'
import { Plus, Trash2, Shield } from 'lucide-react'
import { api, ApiError } from '../api/client'
import { hasPermission, NoAccess } from '../components/RequireAuth'
import type { UserRecord, RoleRecord } from '../types'

export function UsersPage() {
  if (!hasPermission('manage_users')) return <NoAccess permission="manage_users" />
  return <UsersPageInner />
}

function UsersPageInner() {
  const [users, setUsers] = useState<UserRecord[]>([])
  const [roles, setRoles] = useState<RoleRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showCreateUser, setShowCreateUser] = useState(false)
  const [showCreateRole, setShowCreateRole] = useState(false)

  const loadData = async () => {
    try {
      const [u, r] = await Promise.all([api.users.list(), api.roles.list()])
      setUsers(u)
      setRoles(r)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load data.')
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Shield size={20} className="text-[var(--color-primary)]" />
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Users & Roles</h1>
      </div>

      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}

      <div className="max-w-3xl space-y-8">
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">Users</h2>
            <button
              onClick={() => setShowCreateUser(!showCreateUser)}
              className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-border)] transition-colors"
            >
              <Plus size={14} />
              Add User
            </button>
          </div>

          {showCreateUser && (
            <CreateUserForm roles={roles} onCreated={loadData} onClose={() => setShowCreateUser(false)} />
          )}

          <div className="rounded-lg border border-[var(--color-border)] overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[var(--color-border)]/50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-[var(--color-text-muted)]">Username</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-[var(--color-text-muted)]">Role</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-[var(--color-text-muted)]">Created</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-[var(--color-text-muted)]">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-[var(--color-border)]/30">
                    <td className="px-4 py-2 text-[var(--color-text-primary)]">{u.username}</td>
                    <td className="px-4 py-2">
                      <UserRoleSelect
                        userId={u.id}
                        currentRole={u.role_name}
                        roles={roles}
                        onChange={loadData}
                        setPageError={setError}
                      />
                    </td>
                    <td className="px-4 py-2 text-[var(--color-text-muted)] text-xs">{u.created_at?.slice(0, 10)}</td>
                    <td className="px-4 py-2 text-right">
                      <DeleteUserButton userId={u.id} username={u.username} onDeleted={loadData} setPageError={setError} />
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-xs text-[var(--color-text-muted)]">No users found.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">Roles</h2>
            <button
              onClick={() => setShowCreateRole(!showCreateRole)}
              className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-border)] transition-colors"
            >
              <Plus size={14} />
              Create Role
            </button>
          </div>

          {showCreateRole && (
            <CreateRoleForm onCreated={loadData} onClose={() => setShowCreateRole(false)} />
          )}

          <div className="rounded-lg border border-[var(--color-border)] overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[var(--color-border)]/50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-[var(--color-text-muted)]">Name</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-[var(--color-text-muted)]">Permissions</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-[var(--color-text-muted)]">Built-in</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-[var(--color-text-muted)]">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {roles.map((r) => (
                  <tr key={r.name} className="hover:bg-[var(--color-border)]/30">
                    <td className="px-4 py-2 text-[var(--color-text-primary)] font-medium">{r.name}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {r.permissions.map((p) => (
                          <span key={p} className="rounded bg-[var(--color-primary)]/10 px-1.5 py-0.5 text-[10px] text-[var(--color-primary)]">
                            {p}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-[var(--color-text-muted)] text-xs">
                      {r.is_builtin ? 'Yes' : 'No'}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {!r.is_builtin && (
                        <DeleteRoleButton roleName={r.name} onDeleted={loadData} setPageError={setError} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}

function UserRoleSelect({ userId, currentRole, roles, onChange, setPageError }: {
  userId: number
  currentRole: string
  roles: RoleRecord[]
  onChange: () => void
  setPageError: (msg: string | null) => void
}) {
  return (
    <select
      value={currentRole}
      onChange={async (e) => {
        try {
          await api.users.updateRole(userId, e.target.value)
          onChange()
        } catch (err) {
          setPageError(err instanceof ApiError ? err.message : 'Failed to update role.')
        }
      }}
      className="rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1 text-xs text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
    >
      {roles.map((r) => (
        <option key={r.name} value={r.name}>{r.name}</option>
      ))}
    </select>
  )
}

function DeleteUserButton({ userId, username, onDeleted, setPageError }: {
  userId: number
  username: string
  onDeleted: () => void
  setPageError: (msg: string | null) => void
}) {
  const [confirming, setConfirming] = useState(false)

  if (confirming) {
    return (
      <div className="inline-flex items-center gap-1">
        <button
          onClick={async () => {
            try {
              await api.users.delete(userId)
              onDeleted()
            } catch (err) {
              setPageError(err instanceof ApiError ? err.message : 'Failed to delete user.')
            }
            setConfirming(false)
          }}
          className="rounded bg-red-500/20 px-2 py-0.5 text-[10px] text-red-400 hover:bg-red-500/30"
        >
          Confirm
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="rounded px-2 py-0.5 text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      title={`Delete ${username}`}
      className="rounded p-1 text-[var(--color-text-muted)] hover:bg-red-500/10 hover:text-red-400 transition-colors"
    >
      <Trash2 size={14} />
    </button>
  )
}

function DeleteRoleButton({ roleName, onDeleted, setPageError }: {
  roleName: string
  onDeleted: () => void
  setPageError: (msg: string | null) => void
}) {
  const [confirming, setConfirming] = useState(false)

  if (confirming) {
    return (
      <div className="inline-flex items-center gap-1">
        <button
          onClick={async () => {
            try {
              await api.roles.delete(roleName)
              onDeleted()
            } catch (err) {
              setPageError(err instanceof ApiError ? err.message : 'Failed to delete role.')
            }
            setConfirming(false)
          }}
          className="rounded bg-red-500/20 px-2 py-0.5 text-[10px] text-red-400 hover:bg-red-500/30"
        >
          Confirm
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="rounded px-2 py-0.5 text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      title={`Delete ${roleName}`}
      className="rounded p-1 text-[var(--color-text-muted)] hover:bg-red-500/10 hover:text-red-400 transition-colors"
    >
      <Trash2 size={14} />
    </button>
  )
}

const ALL_PERMISSIONS = [
  'view_containers',
  'update_containers',
  'scan_containers',
  'manage_settings',
  'manage_users',
]

function CreateUserForm({ roles, onCreated, onClose }: {
  roles: RoleRecord[]
  onCreated: () => void
  onClose: () => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [roleName, setRoleName] = useState(roles[0]?.name ?? '')
  const [error, setError] = useState<string | null>(null)

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-4 space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <input
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
        />
        <select
          value={roleName}
          onChange={(e) => setRoleName(e.target.value)}
          className="rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
        >
          {roles.map((r) => (
            <option key={r.name} value={r.name}>{r.name}</option>
          ))}
        </select>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex items-center gap-2">
        <button
          onClick={async () => {
            setError(null)
            try {
              await api.users.create(username, password, roleName)
              onCreated()
              onClose()
            } catch (err) {
              setError(err instanceof ApiError ? err.message : 'Failed to create user.')
            }
          }}
          disabled={!username || !password}
          className="rounded-lg bg-[var(--color-primary)] px-4 py-1.5 text-xs font-medium text-black hover:opacity-90 disabled:opacity-50"
        >
          Create
        </button>
        <button
          onClick={onClose}
          className="rounded-lg px-4 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function CreateRoleForm({ onCreated, onClose }: {
  onCreated: () => void
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [perms, setPerms] = useState<Set<string>>(new Set(['view_containers']))
  const [error, setError] = useState<string | null>(null)

  const toggle = (p: string) => {
    const next = new Set(perms)
    if (next.has(p)) next.delete(p)
    else next.add(p)
    setPerms(next)
  }

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-4 space-y-3">
      <input
        type="text"
        placeholder="Role name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
      />
      <div className="flex flex-wrap gap-2">
        {ALL_PERMISSIONS.map((p) => (
          <label
            key={p}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs cursor-pointer transition-colors ${
              perms.has(p)
                ? 'border-[var(--color-primary)] bg-[var(--color-primary)]/10 text-[var(--color-primary)]'
                : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
            }`}
          >
            <input
              type="checkbox"
              checked={perms.has(p)}
              onChange={() => toggle(p)}
              className="sr-only"
            />
            {p}
          </label>
        ))}
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex items-center gap-2">
        <button
          onClick={async () => {
            setError(null)
            try {
              await api.roles.create(name, [...perms])
              onCreated()
              onClose()
            } catch (err) {
              setError(err instanceof ApiError ? err.message : 'Failed to create role.')
            }
          }}
          disabled={!name.trim() || perms.size === 0}
          className="rounded-lg bg-[var(--color-primary)] px-4 py-1.5 text-xs font-medium text-black hover:opacity-90 disabled:opacity-50"
        >
          Create Role
        </button>
        <button
          onClick={onClose}
          className="rounded-lg px-4 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

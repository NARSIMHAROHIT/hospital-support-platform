
import { useEffect, useState } from 'react'
import { Navigate, Outlet } from 'react-router-dom'


export function homeForRole(role) {
  switch (role) {
    case 'patient':
      return '/dashboard'

    case 'doctor':
      return '/doctor/dashboard'

    case 'nurse':
      return '/nurse/dashboard'

    case 'admin':
      return '/admin/dashboard'

    default:
      return '/login'
  }
}


export default function ProtectedRoute({
  allowedRoles = [],
}) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    const controller = new AbortController()

    async function checkSession() {
      try {
        const response = await fetch('/auth/me', {
          credentials: 'include',
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error('Session invalid')
        }

        const data = await response.json()

        if (!controller.signal.aborted) {
          setUser(data)
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          setUser(null)
        }
      } finally {
        if (!controller.signal.aborted) {
          setChecking(false)
        }
      }
    }

    checkSession()

    return () => controller.abort()
  }, [])

  if (checking) {
    return <p style={{ padding: 24 }}>Checking session...</p>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (!allowedRoles.includes(user.role)) {
    return (
      <Navigate to={homeForRole(user.role)} replace />
    )
  }

  return <Outlet context={{ user }} />
}
